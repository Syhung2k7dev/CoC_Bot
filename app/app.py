import json
import math
import os
import re
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request

PATH = Path(__file__).parent
CACHE_PATH = PATH / "data" / "cache.json"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
NOTIFICATION_CACHE_SIZE = 3

app = Flask(__name__)

INSTANCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
EXCLUSION_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
STATE_LOCK = threading.RLock()


def valid_instance_id(value):
    return isinstance(value, str) and INSTANCE_ID_PATTERN.fullmatch(value) is not None


def _backup_corrupt_cache():
    """Move an unreadable or structurally invalid cache aside before recovery."""
    backup_path = CACHE_PATH.with_name(
        f"{CACHE_PATH.name}.corrupt-{time.time_ns()}"
    )
    os.replace(CACHE_PATH, backup_path)
    return backup_path


def get_cache():
    """Load and validate the cache root, preserving invalid files for recovery."""
    if not CACHE_PATH.exists():
        return {"known_instances": {}}

    try:
        with CACHE_PATH.open("r", encoding="utf-8") as cache_file:
            data = json.load(cache_file)
    except (json.JSONDecodeError, UnicodeDecodeError):
        backup_path = _backup_corrupt_cache()
        app.logger.warning("Invalid cache JSON moved to %s", backup_path)
        return {"known_instances": {}}

    if not isinstance(data, dict) or not isinstance(
        data.get("known_instances", {}), dict
    ):
        backup_path = _backup_corrupt_cache()
        app.logger.warning("Invalid cache structure moved to %s", backup_path)
        return {"known_instances": {}}

    data.setdefault("known_instances", {})
    return data


def _valid_number(value, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return minimum is None or value >= minimum


def _instance_from_cache(instance_id, info):
    """Build an Instance from a single cache record, ignoring invalid fields."""
    if not isinstance(info, dict):
        return None

    run_status = info.get("run_status", "")
    if not (
        isinstance(run_status, (str, int, float))
        and not isinstance(run_status, bool)
        and (not isinstance(run_status, str) or len(run_status) <= 64)
        and (not isinstance(run_status, float) or math.isfinite(run_status))
    ):
        run_status = ""

    end_time = info.get("end_time", 0)
    if not _valid_number(end_time, minimum=0):
        end_time = 0

    raw_exclusions = info.get("exclusions", [])
    exclusions = set()
    if isinstance(raw_exclusions, (list, tuple, set)):
        exclusions = {
            item
            for item in raw_exclusions
            if isinstance(item, str) and EXCLUSION_PATTERN.fullmatch(item)
        }

    raw_notifications = info.get("notifications", [])
    notifications = []
    if isinstance(raw_notifications, list):
        for notification in raw_notifications[-NOTIFICATION_CACHE_SIZE:]:
            if not isinstance(notification, dict):
                continue
            timestamp = notification.get("time_stamp")
            if not _valid_number(timestamp, minimum=0):
                continue
            notifications.append({
                "time_stamp": timestamp,
                "data": str(notification.get("data", "")),
            })

    return Instance(
        instance_id,
        run_status=run_status,
        end_time=end_time,
        exclusions=exclusions,
        notifications=notifications,
    )


def _write_cache_atomically(data):
    """Write a complete cache file and atomically replace the previous version."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{CACHE_PATH.name}.",
        suffix=".tmp",
        dir=str(CACHE_PATH.parent),
    )

    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as cache_file:
            json.dump(data, cache_file, indent=4, ensure_ascii=False)
            cache_file.flush()
            os.fsync(cache_file.fileno())
        os.replace(temporary_path, CACHE_PATH)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def update_known_instances():
    """Persist a consistent snapshot of all in-memory instances."""
    with STATE_LOCK:
        data = {
            "known_instances": {
                instance_id: instance.to_dict()
                for instance_id, instance in instances.items()
            }
        }
        _write_cache_atomically(data)


class Instance:
    def __init__(
        self,
        id,
        run_status="",
        end_time=0,
        exclusions=None,
        notifications=None,
    ):
        self.id = id
        self.run_status = run_status
        self.end_time = end_time
        self.exclusions = set(exclusions) if exclusions is not None else set()
        self.notifications = deque(
            notifications or [], maxlen=NOTIFICATION_CACHE_SIZE
        )

    def __eq__(self, other):
        return isinstance(other, Instance) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def to_dict(self):
        return {
            "id": self.id,
            "run_status": self.run_status,
            "end_time": self.end_time,
            "exclusions": sorted(self.exclusions),
            "notifications": list(self.notifications),
        }

    def get_notifications(self, limit=NOTIFICATION_CACHE_SIZE):
        return list(self.notifications)[-limit:]

    def add_notification(self, data):
        with STATE_LOCK:
            self.notifications.append({
                "time_stamp": time.time(),
                "data": str(data),
            })
            update_known_instances()


instances = {}


def get_known_instances():
    with STATE_LOCK:
        instances.clear()
        data = get_cache()
        known_instances = data["known_instances"]

        for instance_id, info in known_instances.items():
            if not valid_instance_id(instance_id):
                app.logger.warning("Ignoring invalid cached instance ID: %r", instance_id)
                continue

            instance = _instance_from_cache(instance_id, info)
            if instance is None:
                app.logger.warning(
                    "Ignoring invalid cache record for instance %s", instance_id
                )
                continue

            instances[instance_id] = instance


@app.route("/", methods=["GET"])
def home():
    return render_template("home.html", ids=sorted(instances.keys()))


@app.route("/instances/<id>", methods=["GET"])
def handle_instance(id):
    instance = instances.get(id)
    if not instance:
        abort(404)
    return render_template(
        "instance.html",
        id=id,
        end_time=instance.end_time,
        current_time=time.time(),
        notifications=instance.get_notifications(),
        exclusions=list(instance.exclusions),
        run_status=instance.run_status,
    )


@app.route("/current_time", methods=["GET"])
def handle_current_time():
    return {"current_time": time.time()}


@app.route("/instances/<id>/end_time", methods=["GET", "POST"])
def handle_end_time(id):
    instance = instances.get(id)
    if not instance:
        abort(404)
    if request.method == "POST":
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"status": "error", "message": "Expected a JSON object"}), 400
        try:
            minutes = int(payload.get("time", 0))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "Invalid time"}), 400
        if not 0 <= minutes <= 10080:
            return jsonify({
                "status": "error",
                "message": "Time must be between 0 and 10080 minutes",
            }), 400
        with STATE_LOCK:
            instance.end_time = minutes * 60 + time.time()
            update_known_instances()

    return {"end_time": instance.end_time}


@app.route("/instances/<id>/running", methods=["GET"])
def handle_running(id):
    instance = instances.get(id)
    if not instance:
        abort(404)
    return {"running": instance.end_time == 0 or instance.end_time < time.time()}


@app.route("/instances/<id>/status", methods=["GET", "POST"])
def handle_status(id):
    instance = instances.get(id)
    if not instance:
        abort(404)
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Expected a JSON object"}), 400
        status = data.get("status", "")
        if (
            not isinstance(status, (str, int, float))
            or isinstance(status, bool)
            or (isinstance(status, str) and len(status) > 64)
            or (isinstance(status, float) and not math.isfinite(status))
        ):
            return jsonify({"status": "error", "message": "Invalid status"}), 400
        with STATE_LOCK:
            instance.run_status = status
            update_known_instances()

    return {"status": instance.run_status}


@app.route("/instances/<id>/exclude", methods=["GET", "POST"])
def handle_exclude(id):
    instance = instances.get(id)
    if not instance:
        abort(404)
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Expected a JSON object"}), 400
        action = data.get("action", "")
        item = data.get("item", "")
        if (
            action not in {"add", "remove"}
            or not isinstance(item, str)
            or not EXCLUSION_PATTERN.fullmatch(item)
        ):
            return jsonify({"status": "error", "message": "Invalid exclusion"}), 400

        with STATE_LOCK:
            changed = False
            if action == "add" and item not in instance.exclusions:
                instance.exclusions.add(item)
                changed = True
            elif action == "remove" and item in instance.exclusions:
                instance.exclusions.remove(item)
                changed = True

            if changed:
                update_known_instances()

    return {"exclusions": sorted(instance.exclusions)}


@app.route("/instances/<id>/notify", methods=["POST"])
def handle_notify(id):
    data = request.get_json(silent=True)
    instance = instances.get(id)
    if not instance:
        abort(404)
    if data is None or len(str(data)) > 1000:
        return jsonify({"status": "error", "message": "Invalid notification"}), 400
    instance.add_notification(data)
    return jsonify({"status": "success", "received": data})


@app.route("/instances/<id>/notifications", methods=["POST"])
def handle_notifications(id):
    n = request.get_json(silent=True)
    instance = instances.get(id)
    if not instance:
        abort(404)
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= NOTIFICATION_CACHE_SIZE:
        return jsonify({"status": "error", "message": "Invalid notification limit"}), 400
    return jsonify(instance.get_notifications(n))


@app.route("/instances", methods=["GET", "POST"])
def handle_instances():
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "Expected a JSON object"}), 400
        instance_id = data.get("id", "")
        if not valid_instance_id(instance_id):
            return jsonify({
                "status": "error",
                "message": "ID must contain 1-64 letters, numbers, underscores or hyphens",
            }), 400

        with STATE_LOCK:
            instance = instances.get(instance_id)
            if instance is None:
                instances[instance_id] = Instance(instance_id)
                update_known_instances()
            elif instance.run_status != "":
                # A fresh registration means this instance is starting again.
                # Preserve pause time, exclusions, and notifications.
                instance.run_status = ""
                update_known_instances()
        return jsonify({"status": "success", "id": instance_id})

    return jsonify({"ids": sorted(instances.keys())})


@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=2592000"
        response.headers.pop("Pragma", None)
        response.headers.pop("Expires", None)
    else:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


get_known_instances()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=1234, debug=False)
