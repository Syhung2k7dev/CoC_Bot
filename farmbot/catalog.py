"""Every picture the bot can use: what it is, where to find it, what it enables.

The window's Pictures tool (Advanced → Pictures), ``farmbot templates`` and the start-up check all
read this list, so a template added to :class:`farmbot.game.T` should get
an entry here too.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from farmbot import imagefile
from farmbot.game import T
from farmbot.vision import TemplateLibrary


@dataclass(frozen=True)
class Picture:
    name: str  # template name, e.g. "buttons/return_home"
    title: str
    where: str  # which screen shows it, and what to drag a box around
    feature: str  # what it enables
    required: bool = False
    folder: bool = False  # a directory of several pictures (one per variant)

    def file_for(self, root: Path, variant: str = "") -> Path:
        if self.folder:
            return root / self.name / f"{variant or 'picture'}.png"
        return root / f"{self.name}.png"


QUICK_EXIT = "Leaving battles without restarting the game"
SNACKS = "Using snacks and potions"
BAT_SPELLS = "Casting only Bat Spells"
QUAKES = "Casting Earthquake Spells"
WARDEN_SIDE = "Putting the Grand Warden with the most troops"
HERO_WALK = "Queen and Champion walks"
SUPER_TROOPS = "Activating super troops"
CAPITAL = "Clan Capital raids"
CLAN_GAMES = "Clan Games"
STAR_PLANS = "War and ranked attacks planned by army and base"
WAR = "Clan war attacks"
APPRENTICE = "Putting the Builder's Apprentice to work"
LAB_ASSISTANT = "Putting the Lab Assistant to work"
TREASURY = "Collecting the Clan Castle treasury"

PICTURES: list[Picture] = [
    # Attacking: without these the bot cannot get into or out of a battle.
    Picture(T.BATTLE, "Battle", "Home village, bottom left: the word \"Battle\".", "Attacking", True, folder=True),
    Picture(T.FIND_MATCH, "Find a Match", "Battle menu: the words \"Find a Match\".", "Attacking", True),
    Picture(T.ARMY_ATTACK, "Attack!", "Army screen after Find a Match: the word \"Attack!\".", "Attacking", True),
    Picture(T.NEXT, "Next", "Scouting a base, bottom right: the word \"Next\".", "Attacking", True),
    Picture(T.BAT_SPELL_CARD, "Bat Spell card", "Troop bar during a battle: the bats and bottle on the "
            "Bat Spell card (not its count or level).", BAT_SPELLS),
    Picture(T.EARTHQUAKE_SPELL_CARD, "Earthquake Spell card", "Troop bar during a battle: the cracked ground "
            "on the Earthquake Spell card (not its count or level).", QUAKES),
    Picture(T.WARDEN_CARD, "Grand Warden card", "Troop bar during a battle: the Grand Warden's face on his "
            "card: just his mouth and beard (not his level, the equipment icon in the corner or the green "
            "button).", WARDEN_SIDE),
    Picture(T.QUEEN_CARD, "Archer Queen card", "Troop bar during a battle: the Archer Queen's face on her "
            "card, eyes to chin (not her level or the pet in the corner).", HERO_WALK),
    Picture(T.CHAMPION_CARD, "Royal Champion card", "Troop bar during a battle: the Royal Champion's face on "
            "her card, eyes to chin (not her level or the pet in the corner).", HERO_WALK),
    Picture(T.HEALER_CARD, "Healer card", "Troop bar during a battle: the Healer on her card: its lower half, "
            "below the \"xN\" count (the count changes) and above the level.", HERO_WALK),
    Picture(T.INVISIBILITY_SPELL_CARD, "Invisibility Spell card", "Troop bar during a battle: the bottle on the "
            "Invisibility Spell card (not its count or level).", HERO_WALK),
    Picture(T.ROCKET_SPEAR, "Rocket Spear", "During a battle, once the Royal Champion is down: the Rocket "
            "Spear's picture over her card (the spear on its purple square, not the square's edge).", HERO_WALK),
    Picture(T.AIR_CARDS, "Air troop cards", "Troop bar during a battle: the picture of an air troop's card "
            "(Dragon, Electro Dragon, Balloon...): its lower half, below the \"xN\" count (the count changes) "
            "and above the level; one picture per troop. With an air army, war and ranked attacks go in "
            "facing the most Air Defenses.", STAR_PLANS, folder=True),
    Picture(T.GROUND_CARDS, "Ground troop cards", "Troop bar during a battle: the picture of a ground troop's "
            "card: its lower half, below the \"xN\" count and above the level; one picture per troop. "
            "With a ground army, the heroes and siege go in first in war and ranked attacks, to open the "
            "way.", STAR_PLANS, folder=True),
    Picture(T.LURE_CARDS, "Lure troop card", "Troop bar during a battle: the picture of a cheap troop's card "
            "(a Barbarian, say). In war and ranked attacks one goes in first, by the Clan Castle, to pull out "
            "its troops.", STAR_PLANS, folder=True),
    Picture(T.AIR_DEFENSE, "Air Defense", "An enemy base in a war or ranked battle, zoomed out (kept in "
            "screens/bases): one Air Defense, just the building; its launcher turns, so a few pictures per "
            "level, at different turns.", STAR_PLANS, folder=True),
    Picture(T.CLAN_CASTLE, "Clan Castle", "An enemy base in a war or ranked battle, zoomed out (kept in "
            "screens/bases): the Clan Castle, just the building; one picture per level. Also blocks it out in "
            "bug report screenshots.", STAR_PLANS, folder=True),
    Picture(T.LOOT_BUILDINGS, "Loot buildings", "An enemy base before a battle, zoomed out (kept in "
            "screens/loot_bases when troops go toward the loot): one storage, mine, collector or drill, just "
            "the building; one picture per kind and level you meet. Optional: elixir is found by its colour "
            "without them; gold and dark elixir buildings only by these.", "Attacking",
            folder=True),
    Picture(T.END_BATTLE, "End Battle", "During a battle, bottom left: the words \"End Battle\" "
            "(\"Surrender\" once units are out).", "Attacking", True, folder=True),
    # Recommended: without these two the bot closes the game to leave a battle.
    Picture(T.SURRENDER_OK, "Okay (end battle)", "After pressing End Battle: the green \"Okay\" in the question box.",
            QUICK_EXIT),
    Picture(T.RETURN_HOME, "Return Home", "Battle result screen: the words \"Return Home\" "
            "(or \"Claim Reward\" when a star bonus is due).", QUICK_EXIT, folder=True),
    Picture(T.EVENT_CHEST, "Event chest room", "After some battles during events: the top half of the arched window "
            "above the chest.", "Opening event chests"),
    Picture(T.CHEST_TAP, "Chest room Tap!", "A chest room without Skip (the Star Bonus chest): the word \"Tap!\" "
            "over the chest.", "Opening event chests"),
    Picture(T.CHEST_SKIP, "Chest room Skip", "Any chest room (its scenery changes with events): the word \"Skip\" "
            "at the bottom right.", "Opening event chests"),
    Picture(T.REMOVE_ADS, "Remove Ads", "An ad shown in the game (\"Welcome Back Chief!\" with another game's "
            "picture): the \"Remove Ads\" badge at its top right, without the X beside it.",
            "Closing ads with their X instead of Okay, which opens the ad"),
    Picture(T.PICK_REWARD, "Pick a Reward", "During event battles (at 30%, 50% and 100% damage): the words "
            "\"Pick a Reward!\" on the red banner above the reward cards.", "Opening event chests"),
    Picture(T.CONTINUE, "Continue", "Under an event chest's reward: the word \"Continue\".", "Opening event chests"),
    # Optional extras
    Picture(T.COLLECT_GOLD, "Full gold mine bubble", "Home village: the gold coin bubble over a full gold mine.",
            "Collecting resources"),
    Picture(T.COLLECT_ELIXIR, "Full elixir collector bubble", "Home village: the pink drop bubble over a full "
            "elixir collector.", "Collecting resources"),
    Picture(T.COLLECT_DARK, "Full dark elixir drill bubble", "Home village: the black drop bubble over a full "
            "dark elixir drill.", "Collecting resources"),
    Picture(T.LOOT_CART, "Loot cart label", "Home village, zoomed out: the word \"Collect\" over the loot cart.",
            "Collecting the loot cart"),
    Picture(T.LOOT_CART_COLLECT, "Loot cart Collect", "After tapping the loot cart: the word \"Collect\" on "
            "the button under it.", "Collecting the loot cart", folder=True),
    Picture(T.SNACK_BOX, "Snack box", "Home village: the box left of Build (snacks and potions), without "
            "the red number on its corner.", SNACKS, folder=True),
    Picture(T.SNACK_USE, "Snack Use ribbon", "After tapping the snack box: the green \"Use\" ribbon over a "
            "snack that can be used.", SNACKS, folder=True),
    Picture(T.SNACK_USE_WINDOW, "Snack window Use", "After tapping a snack with a green ribbon: the word "
            "\"Use\" on the big green button in its window.", SNACKS, folder=True),
    Picture(T.CASTLE_LABEL, "Clan Castle label", "Home village, nothing selected: the white word \"Full!\" or "
            "\"Request\" over your Clan Castle, tight around the word. The castle is found by it, in any clan.",
            TREASURY, folder=True),
    Picture(T.CASTLE_BADGE, "Your Clan Castle's badge", "Optional (for when the castle shows neither \"Full!\" "
            "nor \"Request\"). Home village, zoomed out, nothing selected: your clan's badge over your Clan "
            "Castle, tight around the badge (not the clan name). One per account if their clans differ; kept "
            "on this PC only.", TREASURY, folder=True),
    Picture(T.TREASURY, "Treasury button", "Tap your Clan Castle: the keyhole chest and the word \"Treasury\" on "
            "the button under it.", TREASURY),
    Picture(T.TREASURY_TITLE, "Treasury title", "The window Treasury opens: its title \"Treasury\".", TREASURY),
    Picture(T.TREASURY_COLLECT, "Treasury Collect", "The same window: the word \"Collect\" on its green button.",
            TREASURY),
    Picture(T.TREASURY_CONFIRM, "Collect Resources?", "After Treasury's Collect: the words \"Resources?\" in the "
            "question's title.", TREASURY),
    Picture(T.TREASURY_OKAY, "Okay (Collect Resources?)", "The same question: the word \"Okay\" on its green "
            "button.", TREASURY),
    Picture(T.GRAVESTONE, "Gravestone", "Home village, zoomed out, after someone attacked you: one grey "
            "gravestone, tight around the stone.", "Clearing gravestones"),
    Picture(T.SUPER_ACTIVATE, "Activate (super troop)", "Army screen after Find a Match, with a super troop that "
            "isn't boosted: the word \"Activate\" under its card.", SUPER_TROOPS),
    Picture(T.SUPER_BOOST_TITLE, "Boost? (super troop)", "The window Activate opens: the title \"Boost?\".",
            SUPER_TROOPS),
    Picture(T.SUPER_BOOST_DARK, "Boost with dark elixir", "The same window: the dark elixir drop on the green "
            "button (not the Super Potion).", SUPER_TROOPS),
    Picture(T.BB_HOME_BOAT, "Boat to the builder base", "Home village, bottom left: the boat.", "Builder base"),
    Picture(T.BB_BOAT_MARKER, "Boat marker", "Home village, with a scenery that draws its own boat: the small "
            "sail in the pin above it (just the sail and hull, not the pin's frame).", "Builder base"),
    Picture(T.BB_BUILDER_BOAT, "Boat home", "Builder base, top right: the boat's hull.", "Builder base"),
    Picture(T.BB_BATTLE, "Builder Battle", "Builder base, bottom left: the crossed axes.", "Builder base"),
    Picture(T.BB_FIND_NOW, "Find Now!", "Builder Start Attack window: the words \"Find Now!\".", "Builder base"),
    Picture(T.BB_ATTACK_COOLDOWN, "Attack available in", "Builder Start Attack window after a battle left "
            "early: the words \"Attack available\" over the timer where Find Now! goes.", "Builder base"),
    Picture(T.BB_SEARCH_CANCEL, "Cancel (search)", "Builder base, \"Searching for opponents...\": the word "
            "\"Cancel\" on the red button.", "Builder base"),
    Picture(T.CONFIRM, "Confirm", "A notice such as \"The Event has ended\": the word \"Confirm\" on its green "
            "button.", "Closing notices"),
    Picture(T.GEM, "Gem", "The home village's resource bar: the green gem icon beside your gem count.",
            "Closing notices"),
    Picture(T.STORAGE_MAX, "Max:", "Tap your gold at the top right: the word \"Max:\" in the box that opens.",
            "Storage size"),
    Picture(T.STAR_BONUS_CLAIM, "Claim (Star Bonus)", "The \"Star Bonus received!\" window after the day's "
            "fifth star: the word \"Claim\" on its green button.", "Earning the Star Bonus"),
    Picture(T.STAR_BONUS_DONE, "Star Bonus received", "The home village once the day's Star Bonus is received: "
            "the green check on the Battle button.", "Earning the Star Bonus"),
    Picture(T.STAR_BONUS, "Star Bonus star", "The home village: one star of the five in the strip above the "
            "Battle button (any of them, earned or not).", "Earning the Star Bonus"),
    Picture(T.LAYOUT_OBSTRUCTED, "Defensive Layout obstructed", "The window that sometimes shows after asking "
            "for a battle: its title \"Defensive Layout obstructed\".", "Attacking with an obstructed layout"),
    Picture(T.OBSTRUCTED_ATTACK, "Attack (obstructed layout)", "The same window: the word \"Attack\" on its "
            "green button.", "Attacking with an obstructed layout"),
    Picture(T.UNABLE_TO_ATTACK, "Unable to attack", "The white screen after Find a Match when the last "
            "battle was left without surrendering: the words \"Unable to attack\".", "Searching"),
    Picture(T.LOCKOUT_RETURN_HOME, "Return Home (Unable to attack)", "The same white screen: the words "
            "\"Return Home\" on the portrait button at its bottom left.", "Leaving the Unable to attack screen"),
    Picture(T.ATTACK_COOLDOWN, "Attack available in", "Battle → the battle menu while a battle left midway "
            "still runs: the words \"Attack available in:\" on the grey box where the Battle card's Find a "
            "Match would be.", "Waiting out a battle left midway"),
    Picture(T.SETTINGS_TAB, "Settings tab", "Tap your level badge at the top left: the \"Settings\" tab of the "
            "window that opens (picked, or not).", "Reading the village data", folder=True),
    Picture(T.MORE_SETTINGS, "More Settings", "That Settings tab: the words \"More Settings\" on its button.",
            "Reading the village data"),
    Picture(T.DATA_EXPORT, "Export Village data", "More Settings, at the bottom: the words \"Export Village data "
            "in JSON format\".", "Reading the village data"),
    Picture(T.EXPORT_COPY, "Copy (Data Export)", "The same row: the word \"Copy\" on its green button.",
            "Reading the village data"),
    Picture(T.BB_BATTLE_STARTS, "Battle starts in", "Builder battle, top: \"Battle starts in:\".", "Builder base"),
    Picture(T.BB_BATTLE_ENDS, "Battle ends in", "Builder battle, top: \"Battle ends in:\".", "Builder base"),
    Picture(T.BB_RETURN_HOME, "Return Home (builder)", "Builder battle result: the words \"Return Home\".",
            "Builder base"),
    Picture(T.BB_OKAY, "Okay (Star Bonus)", "Builder base Star Bonus window: the word \"Okay\".", "Builder base"),
    Picture(T.BB_CHANGE_HEROES, "Change Heroes", "Builder battle, after the hero card's swap button: the words "
            "\"Change Heroes\".", "Builder base"),
    Picture(T.SPEED, "1x speed (home)", "Home battle, last minute, right side: the green \"1x\" button.",
            "Battle speed"),
    Picture(T.SPEED_ON, "4x speed (home)", "Home battle, right side: the same button once tapped, reading "
            "\"4x\" (so it isn't tapped back to 1x).", "Battle speed"),
    Picture(T.BB_HERO_MACHINE, "Battle Machine card", "Builder battle, bottom left: the Battle Machine's hero card "
            "(below its health bar).", "Builder base"),
    Picture(T.BB_HERO_COPTER, "Battle Copter card", "Builder battle, bottom left: the Battle Copter's hero card "
            "(below its health bar).", "Builder base"),
    Picture(T.BB_SPEED, "1x speed", "Builder battle, right side: the green \"1x\" button.", "Builder base"),
    Picture(T.BB_COLLECT_GOLD, "Builder gold bubble", "Builder base: the gold bar bubble over a full gold mine.",
            "Builder base"),
    Picture(T.BB_COLLECT_ELIXIR, "Builder elixir bubble", "Builder base: the purple drop bubble over a full "
            "elixir collector (the elixir cart shows the same).", "Builder base"),
    Picture(T.BB_COLLECT_GEMS, "Builder gem bubble", "Builder base: the green gem bubble over a full gem mine.",
            "Builder base"),
    Picture(T.BB_CART_COLLECT, "Elixir Cart Collect", "Elixir Cart window: the word \"Collect\".", "Builder base"),
    Picture(T.BB_CLOCK_READY, "Clock Tower ready", "Builder base: the clock bubble over the Clock Tower.",
            "Builder base"),
    Picture(T.BB_CLOCK_FREE_BOOST, "Free Boost (Clock Tower)", "The selected Clock Tower: the words \"Free "
            "Boost!\" (leave out the time above them).", "Builder base"),
    Picture(T.BB_FREE_BOOST_WINDOW, "Free Boost window", "The window it opens: its title, \"Free Boost!\".",
            "Builder base"),
    Picture(T.BB_FREE_BOOST_CONFIRM, "Free Boost confirm", "That window: the word \"Boost\" on the green button.",
            "Builder base"),
    Picture(T.BB_UPGRADE, "Upgrade (builder)", "Builder base, a selected wall: the word \"Upgrade\".",
            "Builder base walls"),
    Picture(T.BB_UPGRADE_TITLE, "Upgrade to level", "Builder base upgrade window: the words \"Upgrade to\".",
            "Builder base walls"),
    Picture(T.BUILD, "Build", "Home village, bottom right: the word \"Build\" on the hammer button.", "Upgrading walls"),
    Picture(T.GOBLIN, "Goblin Builder", "Home village, over the builder counter above Build: the goblin's face "
            "(shown when only the Goblin Builder, for gems, is left).", "Not paying gems for the Goblin Builder or Researcher"),
    Picture(T.WALL_SUGGESTION, "Wall in Buildings & Heroes", "Build list: the words \"Wall x\" (leave out the "
            "number).", "Upgrading walls"),
    Picture(T.TOWN_HALL_ROW, "Town Hall in Buildings & Heroes", "Build list: the words \"Town Hall\" on its "
            "row (the name only).", "Leaving the Town Hall to you (when that's chosen)"),
    Picture(T.UPGRADE_LOCKED, "Upgrade Locked", "The window a Town Hall that can't be upgraded yet opens: its "
            "title, \"Upgrade Locked\".", "Upgrading the Town Hall"),
    Picture(T.FREE_ROW, "FREE in Buildings & Heroes", "Build list: the word \"FREE\" on a new wall's row.",
            "Building new walls"),
    Picture(T.PLACE_OK, "Build here (tick)", "A new building being put down: the white tick inside its green "
            "button (not the button's edge).", "Building new buildings"),
    Picture(T.PLACE_CANCEL, "Don't build (cross)", "A new building being put down: the white cross inside its "
            "red button (not the button's edge).", "Building new buildings"),
    Picture(T.UPGRADE, "Upgrade", "A selected wall: the word \"Upgrade\" under the hammer.", "Upgrading walls"),
    Picture(T.UPGRADE_CONFIRM, "Confirm (upgrade)", "Upgrade window: the word \"Confirm\" on the green button.",
            "Upgrading walls"),
    Picture(T.HELPER_AVAILABLE, "Available (helper)", "Build list open: the word \"Available\" in a helper's "
            "bubble beside the list.", APPRENTICE),
    Picture(T.APPRENTICE_FACE, "Builder's Apprentice", "Build list open: the Builder's Apprentice's face in his "
            "bubble beside the list.", APPRENTICE),
    Picture(T.APPRENTICE_TITLE, "Builder's Apprentice title", "His window: the words \"Builder's Apprentice\" "
            "(not the level).", APPRENTICE),
    Picture(T.LAB_ASSISTANT_FACE, "Lab Assistant", "Build list's Army Upgrades open: the Lab Assistant's face in "
            "his bubble beside the list.", LAB_ASSISTANT),
    Picture(T.LAB_ASSISTANT_TITLE, "Lab Assistant title", "His window: the words \"Lab Assistant\" (not the level).",
            LAB_ASSISTANT),
    Picture(T.HELPER_ASSIGN, "Assign", "A helper's window: the word \"Assign\" on a row's green button.", APPRENTICE),
    Picture(T.HELPER_KEEP, "Keep assigned (unticked)", "After Assign: the empty box left of \"Keep assigned "
            "until upgrade is complete\".", APPRENTICE),
    Picture(T.HELPER_CONFIRM, "Confirm (helper)", "After Assign: the word \"Confirm\" (not the face beside it).",
            APPRENTICE),
    Picture(T.UPGRADE_MORE, "Upgrade More", "A selected wall: the words \"Upgrade More\" (both lines).",
            "Upgrading walls"),
    Picture(T.ADD_WALL, "Add Wall", "After Upgrade More: the words \"Add Wall\" under a button (the same on "
            "both, +10 and +1, at every wall level).", "Upgrading walls"),
    Picture(T.LIST_FILTER, "List filter", "Build list, left of its title: the slider button.", "Upgrading walls"),
    Picture(T.SORT_COST_MIN, "Cost Min", "Build list filter menu: the word \"Min\" of Cost Min.", "Upgrading walls"),
    Picture(T.SORT_COST_MAX, "Cost Max", "Build list filter menu: the word \"Max\" of Cost Max.", "Upgrading walls"),
    Picture(T.FILTER_GOLD, "Filter: gold", "Build list filter menu: the gold coin.", "Upgrades"),
    Picture(T.FILTER_ELIXIR, "Filter: elixir", "Build list filter menu: the elixir drop.", "Upgrades"),
    Picture(T.FILTER_DARK, "Filter: dark elixir", "Build list filter menu: the dark elixir drop.", "Upgrades"),
    Picture(T.FILTER_ARMY, "Filter: Army", "Build list filter menu: the word \"Army\".", "Upgrades"),
    Picture(T.FILTER_DEFENSE, "Filter: Defense", "Build list filter menu: the word \"Defense\".", "Upgrades"),
    Picture(T.FILTER_HERO, "Filter: Hero", "Build list filter menu: the word \"Hero\".", "Upgrades"),
    Picture(T.FILTER_RESOURCE, "Filter: Resource", "Build list filter menu: the word \"Resource\".", "Upgrades"),
    Picture(T.FILTER_NEW, "Filter: New", "Build list filter menu: the word \"New\".", "Upgrades"),
    Picture(T.FILTER_PERMANENT, "Filter: Permanent", "Build list filter menu: the word \"Permanent\".", "Upgrades"),
    Picture(T.FILTER_TROOPS, "Filter: Troops", "Army Upgrades filter menu: the word \"Troops\".", "Upgrades"),
    Picture(T.FILTER_SPELLS, "Filter: Spells", "Army Upgrades filter menu: the word \"Spells\".", "Upgrades"),
    Picture(T.FILTER_SIEGE, "Filter: Siege", "Army Upgrades filter menu: the word \"Siege\".", "Upgrades"),
    Picture(T.COST_GOLD, "Price: gold", "Build list, right of a row's price: the small gold coin.", "Upgrades"),
    Picture(T.COST_ELIXIR, "Price: elixir", "Build list, right of a row's price: the small elixir drop.", "Upgrades"),
    Picture(T.COST_DARK, "Price: dark elixir", "Build list, right of a row's price: the small dark elixir drop.",
            "Upgrades"),
    Picture(T.BB_FILTER_GOLD, "Filter: builder gold", "Builder base Build list filter menu: the gold bar.",
            "Builder base upgrades"),
    Picture(T.BB_FILTER_ELIXIR, "Filter: builder elixir", "Builder base Build list filter menu: the elixir drop.",
            "Builder base upgrades"),
    Picture(T.BB_COST_GOLD, "Price: builder gold", "Builder base Build list, right of a row's price: the small "
            "gold bar.", "Builder base upgrades"),
    Picture(T.BB_COST_ELIXIR, "Price: builder elixir", "Builder base Build list, right of a row's price: the small "
            "elixir drop.", "Builder base upgrades"),
    Picture(T.CLOSE, "Close (X)", "Any window: the red X in the top right corner.", "Closing windows"),
    Picture(T.OPEN_CHAT, "Open chat", "Home village, left edge: the chat tab arrow.", "Donating"),
    Picture(T.CLOSE_CHAT, "Close chat", "Open chat, right edge: the arrow that closes it.", "Donating"),
    Picture(T.NO_CLAN, "Join A Clan", "Chat panel when you're not in a clan: the words \"Join A Clan\".",
            "Requesting troops"),
    Picture(T.DONATE, "Donate", "Clan chat: the green \"Donate\" button on a request.", "Donating"),
    Picture(T.DONATE_WINDOW, "Donate window", "Clan chat → Donate: the words \"Donation Resource\" at the top of "
            "the window.", "Donating"),
    Picture(T.DONATE_ITEM_DIR, "Unit to donate", "Donate window: the top half of the unit's card (its picture, "
            "without the level or price). Save it under the unit's name, e.g. super_yeti.",
            "Donating", folder=True),
    Picture(T.REQUEST, "Request", "Clan chat, bottom (right of Challenge): the castle with a plus.", "Requesting troops"),
    Picture(T.REQUEST_SEND, "Send request", "Request window: the word \"Send\".", "Requesting troops"),
    Picture(T.EDIT_ARMY, "Edit Army", "Battle menu, bottom left: the words \"Edit Army\" on the green button.",
            "Emptying the Clan Castle"),
    Picture(T.CASTLE_ROW, "Clan Castle row", "Edit Army window, the Clan Castle's row: its first small icon "
            "(the castle with a troop), left of the troop count.", "Emptying the Clan Castle"),
    Picture(T.CASTLE_TRASH, "Clan Castle bin", "Edit Army window, with troops in the Clan Castle: the bin at the "
            "right end of the Clan Castle's row.", "Emptying the Clan Castle"),
    Picture(T.CASTLE_REQUEST, "Army window Request", "Edit Army window, right of Add, while a request is free: the "
            "castle with the \"+\" bubble on the green button.", "Emptying the Clan Castle"),
    Picture(T.REMOVE_TROOPS, "Remove troops?", "After tapping that bin: the title \"Remove troops?\".",
            "Emptying the Clan Castle"),
    Picture(T.CAPITAL_BADGE, "Raid badge", "Home village, over the capital airship: the sword on the red badge "
            "(raids left; a gold sword for the bonus raid).", CAPITAL, folder=True),
    Picture(T.CAPITAL_COLLAPSE, "Fold event buttons", "Home village, bottom: the \"<\" at the end of the event "
            "buttons.", CAPITAL),
    Picture(T.CAPITAL_AIRSHIP, "Capital airship", "Home village, bottom left (event buttons folded): the airship's "
            "balloons, without the badge. Only needed when no raid badge shows (the badge finds the airship "
            "otherwise); the airship's look changes, so add a picture of each look.", CAPITAL, folder=True),
    Picture(T.CAPITAL_START_RAID, "Start Raid", "Clan Capital before the clan's raid began, bottom right: the "
            "crossed swords and \"Start Raid\".", CAPITAL),
    Picture(T.CAPITAL_NEXT_RAID, "Next Raid", "Clan Capital, after a raid's summary: the words \"Next Raid\".",
            CAPITAL),
    Picture(T.CAPITAL_RAID_MAP, "Raid Map", "Clan Capital, bottom right: the words \"Raid Map\".", CAPITAL),
    Picture(T.CAPITAL_LEAVE_RAID, "Raid map: Map", "Raid map, bottom left: the airship \"Map\" button.", CAPITAL),
    Picture(T.CAPITAL_RETURN_HOME, "Capital: Return Home", "Clan Capital, bottom left: the words \"Return Home\".",
            CAPITAL),
    Picture(T.CAPITAL_DISTRICT_ATTACK, "District Attack", "Raid map, after tapping a district: the red \"Attack\".",
            CAPITAL),
    Picture(T.CAPITAL_ATTACK_NOW, "Attack Now?", "Raid map → Attack: the title \"Attack Now?\".", CAPITAL),
    Picture(T.CAPITAL_ATTACK_GO, "Raid Attack", "\"Attack Now?\" window: the green \"Attack\".", CAPITAL),
    Picture(T.CAPITAL_SURE_ATTACK, "Attack anyway", "\"Capital Gold storage is full\" question: \"Attack\".", CAPITAL),
    Picture(T.CAPITAL_NOT_MEMBER, "Not a member yet", "\"Only members who were in the Clan before the Raid Weekend "
            "began can attack\": its words.", CAPITAL),
    Picture(T.CAPITAL_CARD_DIR, "Capital unit", "Change Capital Army list: the unit's picture, in colour (it tells the "
            "cards in the raid's troop bar apart). Save it under the unit's name, e.g. super_miner.", CAPITAL, folder=True),
    Picture(T.CAPITAL_BATTLE_HEAL, "Raid Heal card", "Troop bar during a raid: the Heal Spell card's bottle, below its count "
            "(the count changes).",
            CAPITAL),
    Picture(T.CAPITAL_RESULT_MAP, "Raid result: Map", "Raid result screen: the word \"Map\".", CAPITAL),
    Picture(T.CG_ICON, "Clan Games button", "Home village, bottom: the bearded builder among the event buttons.",
            CLAN_GAMES),
    Picture(T.CG_UNFOLD, "Unfold event buttons", "Home village, bottom (event buttons folded): the \">\" after "
            "them.", CLAN_GAMES),
    Picture(T.CG_CHOOSE, "Clan Games: Choose", "Home village, top left, over the Clan Games caravan while no "
            "challenge is going: the word \"Choose\".", CLAN_GAMES),
    Picture(T.CG_TITLE, "Clan Games sign", "Clan Games board, top left: the words \"Clan Games\".", CLAN_GAMES),
    Picture(T.CG_CHALLENGES_TAB, "Challenges tab", "Clan Games board, top: the word \"Challenges\".", CLAN_GAMES),
    Picture(T.CG_REWARDS_TAB, "Rewards tab", "Clan Games board, top: the word \"Rewards\" (the tab not picked).",
            CLAN_GAMES),
    Picture(T.CG_MEDAL, "Challenge medal", "Clan Games board: the silver medal after a challenge's points, in "
            "colour.", CLAN_GAMES),
    Picture(T.CG_GOING, "Challenge going", "Clan Games board, with a challenge going: the stopwatch at the top left "
            "of its tile.", CLAN_GAMES),
    Picture(T.CG_NOTE, "Challenge Progress note", "Home village, bottom right, for a few seconds after a battle "
            "that helped the challenge going: the words \"Challenge Progress\".", CLAN_GAMES),
    Picture(T.CG_START, "Challenge Start", "Clan Games board → a challenge: the word \"Start\" on the green "
            "button.", CLAN_GAMES),
    Picture(T.CG_TRASH, "Challenge Trash", "Clan Games board → the challenge going: \"Trash\" and the dynamite "
            "on the red button.", CLAN_GAMES),
    Picture(T.CG_TRASH_TITLE, "Trash Challenge?", "After Trash: the title \"Trash Challenge?\".", CLAN_GAMES),
    Picture(T.CG_CLOSE, "Clan Games close", "Clan Games board, top right: the red X.", CLAN_GAMES),
    Picture(T.CG_INFO, "Reward item", "Clan Games board, Rewards tab: the \"i\" on an item's reward; add one in "
            "colour and one greyed.", CLAN_GAMES, folder=True),
    Picture(T.WAR_BUTTON, "War button", "Home village, left edge, during a war: the middle of the crossed swords "
            "(not the red badge or the timer).", WAR),
    Picture(T.WAR_RETURN_HOME, "War: Return Home", "War map, bottom left: the words \"Return Home\".", WAR),
    Picture(T.WAR_BATTLE_DAY, "Battle Day", "War map, under the timer at the top: the words \"Battle Day\".", WAR),
    Picture(T.WAR_TO_ENEMY, "War map: Enemy", "Your clan's war map, right edge: the word \"Enemy\" on the "
            "arrow button.", WAR),
    Picture(T.WAR_TO_HOME, "War map: Home", "The enemy's war map, right edge: the word \"Home\" on the arrow "
            "button.", WAR),
    Picture(T.WAR_RECOMMENDED, "Recommended target", "The enemy's war map: the words \"Recommended target\" "
            "under a base.", WAR),
    Picture(T.WAR_ATTACK, "War Attack!", "A tapped enemy base's panel: the word \"Attack!\" on the orange "
            "button.", WAR),
    Picture(T.WAR_ARMY_ATTACK, "War army: Attack!", "The war army's window (after a base's Attack!): the word "
            "\"Attack!\" on the green button, bottom right.", WAR),
    Picture(T.WAR_CONFIRM_TITLE, "Confirm Attack", "After the war army's Attack!: the title \"Confirm Attack\".", WAR),
    Picture(T.WAR_CONFIRM_ATTACK, "Confirm Attack: Attack!", "The \"Confirm Attack\" question: the word "
            "\"Attack!\" on its green button.", WAR),
    Picture(T.WAR_SCOUT, "War Scout", "A tapped enemy base's panel: the word \"Scout\" on the green button.", WAR),
    Picture(T.TRY_AGAIN, "Try Again", "Connection lost popup: \"Try Again\".", "Recovering from disconnects"),
    Picture(T.RELOAD, "Reload", "\"Another device is connected\" popup: \"Reload\".", "Recovering from disconnects"),
    Picture(T.NEW_CONTENT, "New Content", "The \"New Content\" window (the game updated while running, met "
            "after Find a Match): its title.", "Refreshing the game for new content"),
    Picture(T.NEW_CONTENT_REFRESH, "New Content: Refresh", "The word \"Refresh\" on the \"New Content\" "
            "window's green button.", "Refreshing the game for new content"),
    Picture(T.LOGIN, "Not logged in", "The game's start screen with no account logged in: \"Log in with Supercell ID\".",
            "Stopping when the game isn't logged in"),
    Picture(T.RATE_TITLE, "Rate Clash of Clans", "The title of Google Play's \"Rate Clash of Clans\" dialog, "
            "which can pop up over the game.", "Closing the rate-the-game dialog"),
    Picture(T.RATE_NEVER, "Rate dialog: Never", "NEVER, at the bottom of Google Play's \"Rate Clash of Clans\" "
            "dialog.", "Closing the rate-the-game dialog"),
    Picture(T.MAINTENANCE, "Maintenance break", "The yellow \"Maintenance break\" banner at the top of the "
            "news screen the game shows during a maintenance break.", "Stopping during a maintenance break"),
]
BY_NAME = {p.name: p for p in PICTURES}


def present(library: TemplateLibrary, picture: Picture) -> bool:
    return library.has(picture.name)


def slow_exit(library: TemplateLibrary) -> bool:
    """True when battles will be left by closing the game."""
    return any(not present(library, p) for p in PICTURES if p.feature == QUICK_EXIT)


def missing(library: TemplateLibrary, required_only: bool = False) -> list[Picture]:
    return [p for p in PICTURES if (p.required or not required_only) and not present(library, p)]


def lookalike_score(screen: np.ndarray, crop: np.ndarray) -> float:
    """The best match for a fresh crop anywhere on ``screen`` other than
    where it was cut from. Near or above the bot's threshold (0.85) means
    the picture could be mistaken for something else: crop it tighter."""
    h, w = crop.shape[:2]
    scores = cv2.matchTemplate(screen, crop, cv2.TM_CCOEFF_NORMED)
    _, _, _, (bx, by) = cv2.minMaxLoc(scores)
    scores[max(0, by - h // 2):by + h // 2 + 1, max(0, bx - w // 2):bx + w // 2 + 1] = -1
    return float(scores.max())


def save_crop(root: Path, picture: Picture, crop: np.ndarray, variant: str = "") -> Path:
    path = picture.file_for(root, variant)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not imagefile.write(str(path), crop):
        raise OSError(f"could not write {path}")
    return path
