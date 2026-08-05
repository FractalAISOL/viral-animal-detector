"""Species, name, and location extraction from Reddit post titles."""

import re
import logging

logger = logging.getLogger(__name__)

# --- Species mapping: term -> (canonical_species, category) ---
# ~200 canonical species from ~580 input terms
SPECIES_MAP = {
    # Dogs
    "dog": ("dog", "domestic"), "dogs": ("dog", "domestic"), "puppy": ("dog", "domestic"),
    "puppies": ("dog", "domestic"), "pupper": ("dog", "domestic"), "doggo": ("dog", "domestic"),
    "pup": ("dog", "domestic"), "pups": ("dog", "domestic"), "goodboy": ("dog", "domestic"),
    "good boy": ("dog", "domestic"), "good girl": ("dog", "domestic"),
    "golden retriever": ("golden retriever", "domestic"), "labrador": ("labrador", "domestic"),
    "lab": ("labrador", "domestic"), "german shepherd": ("german shepherd", "domestic"),
    "husky": ("husky", "domestic"), "corgi": ("corgi", "domestic"),
    "pitbull": ("pitbull", "domestic"), "pit bull": ("pitbull", "domestic"),
    "bulldog": ("bulldog", "domestic"), "poodle": ("poodle", "domestic"),
    "chihuahua": ("chihuahua", "domestic"), "beagle": ("beagle", "domestic"),
    "dachshund": ("dachshund", "domestic"), "shiba": ("shiba inu", "domestic"),
    "shiba inu": ("shiba inu", "domestic"), "rottweiler": ("rottweiler", "domestic"),
    "dalmatian": ("dalmatian", "domestic"), "border collie": ("border collie", "domestic"),
    "greyhound": ("greyhound", "domestic"), "mastiff": ("mastiff", "domestic"),
    "great dane": ("great dane", "domestic"), "akita": ("akita", "domestic"),
    "malinois": ("malinois", "domestic"), "samoyed": ("samoyed", "domestic"),
    "newfoundland": ("newfoundland dog", "domestic"), "bernese": ("bernese mountain dog", "domestic"),
    "boxer": ("boxer dog", "domestic"), "pomeranian": ("pomeranian", "domestic"),
    "schnauzer": ("schnauzer", "domestic"), "whippet": ("whippet", "domestic"),
    "weimaraner": ("weimaraner", "domestic"), "vizsla": ("vizsla", "domestic"),
    "basenji": ("basenji", "domestic"), "mutt": ("dog", "domestic"),
    # Cats
    "cat": ("cat", "domestic"), "cats": ("cat", "domestic"), "kitten": ("cat", "domestic"),
    "kittens": ("cat", "domestic"), "kitty": ("cat", "domestic"), "kitties": ("cat", "domestic"),
    "catto": ("cat", "domestic"), "meow": ("cat", "domestic"),
    "tabby": ("tabby cat", "domestic"), "calico": ("calico cat", "domestic"),
    "siamese": ("siamese cat", "domestic"), "persian": ("persian cat", "domestic"),
    "maine coon": ("maine coon", "domestic"), "ragdoll": ("ragdoll", "domestic"),
    "sphynx": ("sphynx cat", "domestic"), "bengal cat": ("bengal cat", "domestic"),
    "british shorthair": ("british shorthair", "domestic"),
    "scottish fold": ("scottish fold", "domestic"),
    "russian blue": ("russian blue", "domestic"),
    "orange cat": ("orange cat", "domestic"), "tuxedo cat": ("tuxedo cat", "domestic"),
    "black cat": ("black cat", "domestic"),
    # Zoo / exotic mammals
    "hippo": ("hippo", "zoo"), "hippopotamus": ("hippo", "zoo"),
    "pygmy hippo": ("pygmy hippo", "zoo"), "pygmy hippopotamus": ("pygmy hippo", "zoo"),
    "elephant": ("elephant", "wildlife"), "elephants": ("elephant", "wildlife"),
    "giraffe": ("giraffe", "wildlife"), "giraffes": ("giraffe", "wildlife"),
    "zebra": ("zebra", "wildlife"), "lion": ("lion", "wildlife"),
    "lions": ("lion", "wildlife"), "lioness": ("lion", "wildlife"),
    "tiger": ("tiger", "wildlife"), "tigers": ("tiger", "wildlife"),
    "leopard": ("leopard", "wildlife"), "cheetah": ("cheetah", "wildlife"),
    "jaguar": ("jaguar", "wildlife"), "panther": ("panther", "wildlife"),
    "panda": ("panda", "wildlife"), "pandas": ("panda", "wildlife"),
    "giant panda": ("giant panda", "wildlife"), "red panda": ("red panda", "wildlife"),
    "koala": ("koala", "wildlife"), "koalas": ("koala", "wildlife"),
    "kangaroo": ("kangaroo", "wildlife"), "kangaroos": ("kangaroo", "wildlife"),
    "wallaby": ("wallaby", "wildlife"),
    "gorilla": ("gorilla", "wildlife"), "gorillas": ("gorilla", "wildlife"),
    "orangutan": ("orangutan", "wildlife"), "orangutans": ("orangutan", "wildlife"),
    "chimpanzee": ("chimpanzee", "wildlife"), "chimp": ("chimpanzee", "wildlife"),
    "monkey": ("monkey", "wildlife"), "monkeys": ("monkey", "wildlife"),
    "macaque": ("macaque", "wildlife"), "baboon": ("baboon", "wildlife"),
    "capybara": ("capybara", "wildlife"), "capybaras": ("capybara", "wildlife"),
    "sloth": ("sloth", "wildlife"), "sloths": ("sloth", "wildlife"),
    "otter": ("otter", "wildlife"), "otters": ("otter", "wildlife"),
    "sea otter": ("sea otter", "wildlife"),
    "beaver": ("beaver", "wildlife"), "platypus": ("platypus", "wildlife"),
    "wombat": ("wombat", "wildlife"), "quokka": ("quokka", "wildlife"),
    "armadillo": ("armadillo", "wildlife"), "anteater": ("anteater", "wildlife"),
    "tapir": ("tapir", "wildlife"), "rhino": ("rhino", "wildlife"),
    "rhinoceros": ("rhino", "wildlife"),
    # Bears
    "bear": ("bear", "wildlife"), "bears": ("bear", "wildlife"),
    "polar bear": ("polar bear", "wildlife"), "grizzly": ("grizzly bear", "wildlife"),
    "grizzly bear": ("grizzly bear", "wildlife"), "brown bear": ("brown bear", "wildlife"),
    "black bear": ("black bear", "wildlife"), "sun bear": ("sun bear", "wildlife"),
    # Marine
    "whale": ("whale", "marine"), "whales": ("whale", "marine"),
    "dolphin": ("dolphin", "marine"), "dolphins": ("dolphin", "marine"),
    "orca": ("orca", "marine"), "shark": ("shark", "marine"),
    "sharks": ("shark", "marine"), "great white": ("great white shark", "marine"),
    "hammerhead": ("hammerhead shark", "marine"),
    "seal": ("seal", "marine"), "seals": ("seal", "marine"),
    "sea lion": ("sea lion", "marine"), "walrus": ("walrus", "marine"),
    "manatee": ("manatee", "marine"), "octopus": ("octopus", "marine"),
    "jellyfish": ("jellyfish", "marine"), "starfish": ("starfish", "marine"),
    "seahorse": ("seahorse", "marine"), "manta ray": ("manta ray", "marine"),
    "stingray": ("stingray", "marine"),
    # Birds
    "bird": ("bird", "bird"), "birds": ("bird", "bird"),
    "parrot": ("parrot", "bird"), "parrots": ("parrot", "bird"),
    "cockatoo": ("cockatoo", "bird"), "cockatiel": ("cockatiel", "bird"),
    "budgie": ("budgie", "bird"), "parakeet": ("parakeet", "bird"),
    "macaw": ("macaw", "bird"), "eagle": ("eagle", "bird"),
    "bald eagle": ("bald eagle", "bird"), "hawk": ("hawk", "bird"),
    "falcon": ("falcon", "bird"), "owl": ("owl", "bird"),
    "owls": ("owl", "bird"), "penguin": ("penguin", "bird"),
    "penguins": ("penguin", "bird"), "flamingo": ("flamingo", "bird"),
    "flamingos": ("flamingo", "bird"), "pelican": ("pelican", "bird"),
    "heron": ("heron", "bird"), "crane": ("crane", "bird"),
    "crow": ("crow", "bird"), "crows": ("crow", "bird"),
    "raven": ("raven", "bird"), "magpie": ("magpie", "bird"),
    "swan": ("swan", "bird"), "swans": ("swan", "bird"),
    "duck": ("duck", "bird"), "ducks": ("duck", "bird"),
    "duckling": ("duck", "bird"), "ducklings": ("duck", "bird"),
    "goose": ("goose", "bird"), "geese": ("goose", "bird"),
    "chicken": ("chicken", "bird"), "chickens": ("chicken", "bird"),
    "rooster": ("rooster", "bird"), "hen": ("hen", "bird"),
    "turkey": ("turkey bird", "bird"), "peacock": ("peacock", "bird"),
    "hummingbird": ("hummingbird", "bird"), "woodpecker": ("woodpecker", "bird"),
    "robin": ("robin", "bird"), "sparrow": ("sparrow", "bird"),
    "pigeon": ("pigeon", "bird"), "dove": ("dove", "bird"),
    "toucan": ("toucan", "bird"), "stork": ("stork", "bird"),
    "kingfisher": ("kingfisher", "bird"), "kookaburra": ("kookaburra", "bird"),
    # Reptiles / amphibians
    "snake": ("snake", "reptile"), "snakes": ("snake", "reptile"),
    "python": ("python snake", "reptile"), "cobra": ("cobra", "reptile"),
    "viper": ("viper", "reptile"), "rattlesnake": ("rattlesnake", "reptile"),
    "boa": ("boa", "reptile"),
    "lizard": ("lizard", "reptile"), "lizards": ("lizard", "reptile"),
    "gecko": ("gecko", "reptile"), "iguana": ("iguana", "reptile"),
    "chameleon": ("chameleon", "reptile"), "bearded dragon": ("bearded dragon", "reptile"),
    "komodo": ("komodo dragon", "reptile"), "komodo dragon": ("komodo dragon", "reptile"),
    "monitor lizard": ("monitor lizard", "reptile"),
    "turtle": ("turtle", "reptile"), "turtles": ("turtle", "reptile"),
    "tortoise": ("tortoise", "reptile"), "sea turtle": ("sea turtle", "reptile"),
    "crocodile": ("crocodile", "reptile"), "croc": ("crocodile", "reptile"),
    "alligator": ("alligator", "reptile"), "gator": ("alligator", "reptile"),
    "frog": ("frog", "amphibian"), "frogs": ("frog", "amphibian"),
    "toad": ("toad", "amphibian"), "salamander": ("salamander", "amphibian"),
    "axolotl": ("axolotl", "amphibian"),
    # Small mammals
    "rabbit": ("rabbit", "domestic"), "rabbits": ("rabbit", "domestic"),
    "bunny": ("rabbit", "domestic"), "bunnies": ("rabbit", "domestic"),
    "hamster": ("hamster", "domestic"), "hamsters": ("hamster", "domestic"),
    "guinea pig": ("guinea pig", "domestic"), "gerbil": ("gerbil", "domestic"),
    "ferret": ("ferret", "domestic"), "ferrets": ("ferret", "domestic"),
    "chinchilla": ("chinchilla", "domestic"), "hedgehog": ("hedgehog", "domestic"),
    "hedgehogs": ("hedgehog", "domestic"), "rat": ("rat", "domestic"),
    "rats": ("rat", "domestic"), "mouse": ("mouse", "domestic"),
    "mice": ("mouse", "domestic"), "hammy": ("hamster", "domestic"),
    # Wild small mammals
    "squirrel": ("squirrel", "wildlife"), "squirrels": ("squirrel", "wildlife"),
    "chipmunk": ("chipmunk", "wildlife"), "raccoon": ("raccoon", "wildlife"),
    "raccoons": ("raccoon", "wildlife"), "fox": ("fox", "wildlife"),
    "foxes": ("fox", "wildlife"), "wolf": ("wolf", "wildlife"),
    "wolves": ("wolf", "wildlife"), "coyote": ("coyote", "wildlife"),
    "deer": ("deer", "wildlife"), "moose": ("moose", "wildlife"),
    "elk": ("elk", "wildlife"), "bison": ("bison", "wildlife"),
    "buffalo": ("buffalo", "wildlife"),
    "badger": ("badger", "wildlife"), "skunk": ("skunk", "wildlife"),
    "opossum": ("opossum", "wildlife"), "possum": ("possum", "wildlife"),
    "porcupine": ("porcupine", "wildlife"), "mole": ("mole", "wildlife"),
    "bat": ("bat", "wildlife"), "bats": ("bat", "wildlife"),
    # Insects / arachnids
    "spider": ("spider", "arachnid"), "tarantula": ("tarantula", "arachnid"),
    "scorpion": ("scorpion", "arachnid"),
    "bee": ("bee", "insect"), "bees": ("bee", "insect"),
    "butterfly": ("butterfly", "insect"), "butterflies": ("butterfly", "insect"),
    "moth": ("moth", "insect"), "dragonfly": ("dragonfly", "insect"),
    "mantis": ("mantis", "insect"), "praying mantis": ("mantis", "insect"),
    "beetle": ("beetle", "insect"), "ladybug": ("ladybug", "insect"),
    "ant": ("ant", "insect"), "ants": ("ant", "insect"),
    "caterpillar": ("caterpillar", "insect"),
    # Fish
    "fish": ("fish", "fish"), "goldfish": ("goldfish", "fish"),
    "betta": ("betta", "fish"), "koi": ("koi", "fish"),
    "clownfish": ("clownfish", "fish"), "pufferfish": ("pufferfish", "fish"),
    # Misc
    "horse": ("horse", "domestic"), "horses": ("horse", "domestic"),
    "pony": ("pony", "domestic"), "donkey": ("donkey", "domestic"),
    "mule": ("mule", "domestic"), "pig": ("pig", "domestic"),
    "pigs": ("pig", "domestic"), "piglet": ("pig", "domestic"),
    "goat": ("goat", "domestic"), "goats": ("goat", "domestic"),
    "sheep": ("sheep", "domestic"), "lamb": ("sheep", "domestic"),
    "cow": ("cow", "domestic"), "cows": ("cow", "domestic"),
    "calf": ("cow", "domestic"), "bull": ("bull", "domestic"),
    "llama": ("llama", "domestic"), "alpaca": ("alpaca", "domestic"),
    # Generic
    "chonk": ("animal", "generic"), "chonker": ("animal", "generic"),
    "animal": ("animal", "generic"), "animals": ("animal", "generic"),
    "pet": ("animal", "generic"), "pets": ("animal", "generic"),
    "creature": ("animal", "generic"), "critter": ("animal", "generic"),
    "baby animal": ("animal", "generic"), "rescue": ("animal", "generic"),
    "stray": ("animal", "generic"), "wildlife": ("animal", "generic"),
}

# Ambiguous terms that need subreddit context
AMBIGUOUS_TERMS = {
    "python", "boxer", "crane", "robin", "bat", "bull", "ram",
    "cardinal", "mustang", "jaguar", "viper", "cobra", "falcon",
    "hawk", "raven", "bear", "tiger", "lion", "panther", "eagle",
    "dolphin", "seal", "turkey",
}

ANIMAL_SUBREDDITS = {
    "aww", "eyebleach", "animalsbeingderps", "animalsbeingbros",
    "natureisfuckinglit", "absoluteunits", "cats", "dogs",
    "animalsbeingjerks", "whatswrongwithyourdog", "natureismetal",
    "rarepuppers",
}

NON_ANIMAL_SUBREDDITS = {
    "programming", "boxing", "nfl", "nba", "music", "cars",
    "hardware", "baseball", "cricket", "formula1", "soccer",
    "leagueoflegends", "nascar", "mma", "ufc",
}

# Build regex pattern for species names (sorted longest first to match multi-word first)
_species_terms_sorted = sorted(SPECIES_MAP.keys(), key=len, reverse=True)
SPECIES_PATTERN = "|".join(re.escape(t) for t in _species_terms_sorted)

# --- Name extraction patterns ---
NAME_BLACKLIST = {
    "the", "this", "that", "what", "why", "how", "when", "where", "who",
    "just", "look", "see", "watch", "can", "does", "did", "has", "have",
    "breaking", "update", "news", "alert", "warning", "help", "please",
    "urgent", "psa", "til", "tifu", "oc", "rant", "reminder", "official",
    "confirmed", "megathread",
    "my", "our", "your", "his", "her", "its", "their",
    "new", "old", "big", "little", "baby", "cute", "rare",
    "today", "yesterday", "finally", "apparently", "literally",
    "ever", "never", "always", "still", "now", "here", "there",
    "everyone", "someone", "anyone", "nobody", "nothing",
    "omg", "wow", "holy", "oh", "damn", "lol", "lmao",
    "a", "an", "i", "me", "we", "he", "she", "it", "they",
    "is", "are", "was", "were", "be", "been", "being",
    "so", "very", "much", "really", "not", "no", "yes",
}

NAME_PATTERNS = [
    # 1. "Meet X, the [species]" / "Meet X the [species]"
    re.compile(r'meet\s+(.+?)\s*[,.]?\s*(?:the|a|an)\s', re.IGNORECASE),
    # 2. "X the [species]" at start
    re.compile(r'^(.+?)\s+the\s+(?:' + SPECIES_PATTERN + r')', re.IGNORECASE),
    # 3. "This is X" / "Say hello to X" / "Introducing X"
    re.compile(r'(?:this is|say (?:hello|hi) to|introducing|everyone meet)\s+(.+?)(?:\s*[,!.]|\s+the\s|\s+who|\s+and)', re.IGNORECASE),
    # 4. "[species] named/called/nicknamed X"
    re.compile(r'(?:named|called|dubbed|nicknamed|known as)\s+(.+?)(?:\s*[,!.]|\s+(?:who|and|is|was|has|after)|\s*$)', re.IGNORECASE),
    # 5. "RIP X" / "Rest in peace X"
    re.compile(r'(?:rip|rest in peace|farewell|goodbye|rip to)\s+(.+?)(?:\s*[,!.]|\s+the\s|\s*$)', re.IGNORECASE),
    # 6. "X update" / "X news" / "X is..."
    re.compile(r'^(.+?)\s+(?:update|news|watch|alert|is\s)', re.IGNORECASE),
    # 7. "My/Our [species] X" — most common Reddit format
    re.compile(r'(?:my|our|his|her|their)\s+(?:' + SPECIES_PATTERN + r')\s+(.+?)(?:\s+(?:just|is|was|did|has|had|does|got|went|loves|hates|found|ate|broke|met|turned)|\s*[,!.])', re.IGNORECASE),
    # 8. "X, the/a [species] from/at/in [location]"
    re.compile(r'^(.+?),?\s+(?:the|a|an)\s+(?:' + SPECIES_PATTERN + r')\s+(?:from|at|in|of)\s', re.IGNORECASE),
]

# Simple suffix stripping for normalization
_SUFFIX_MAP = {
    "ing": "", "ies": "y", "es": "", "s": "",
    "ed": "", "ly": "", "er": "", "est": "",
}


def _normalize_term(word: str) -> str:
    """Simple suffix stripping for matching."""
    w = word.lower()
    for suffix, replacement in _SUFFIX_MAP.items():
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            candidate = w[:-len(suffix)] + replacement
            if candidate in SPECIES_MAP:
                return candidate
    return w


def detect_species(title: str, subreddit: str) -> tuple[str, str] | None:
    """
    Detect animal species from title.
    Returns (canonical_species, category) or None.
    """
    title_lower = title.lower()
    sub_lower = subreddit.lower()

    # Try multi-word matches first (longest first)
    for term in _species_terms_sorted:
        if term in title_lower:
            # Check ambiguity
            if term in AMBIGUOUS_TERMS:
                if sub_lower in NON_ANIMAL_SUBREDDITS:
                    continue
                if sub_lower not in ANIMAL_SUBREDDITS:
                    # General sub — need second animal signal
                    other_terms = [t for t in SPECIES_MAP if t != term and t in title_lower]
                    animal_keywords = ["pet", "rescue", "zoo", "animal", "wild", "adopted", "stray"]
                    has_signal = other_terms or any(kw in title_lower for kw in animal_keywords)
                    if not has_signal:
                        continue
            return SPECIES_MAP[term]

    # Try normalized words
    for word in title_lower.split():
        normalized = _normalize_term(word)
        if normalized in SPECIES_MAP and normalized not in AMBIGUOUS_TERMS:
            return SPECIES_MAP[normalized]

    return None


def extract_name(title: str) -> str | None:
    """Extract animal name from title using 8 regex patterns."""
    for pattern in NAME_PATTERNS:
        match = pattern.search(title)
        if match:
            name = match.group(1).strip().strip(",!.?'\"")
            # Clean up
            if len(name) < 2 or len(name) > 40:
                continue
            # Check against blacklist
            if name.lower() in NAME_BLACKLIST:
                continue
            # Skip if all lowercase common words
            words = name.split()
            if all(w.lower() in NAME_BLACKLIST for w in words):
                continue
            return name
    return None


# --- Location extraction ---
ZOO_NAMES = {
    "san diego zoo": "San Diego",
    "bronx zoo": "New York",
    "national zoo": "Washington DC",
    "smithsonian zoo": "Washington DC",
    "london zoo": "London",
    "chester zoo": "Chester",
    "edinburgh zoo": "Edinburgh",
    "taronga zoo": "Sydney",
    "melbourne zoo": "Melbourne",
    "australia zoo": "Queensland",
    "singapore zoo": "Singapore",
    "night safari": "Singapore",
    "ueno zoo": "Tokyo",
    "asahiyama zoo": "Asahikawa",
    "beijing zoo": "Beijing",
    "toronto zoo": "Toronto",
    "calgary zoo": "Calgary",
    "berlin zoo": "Berlin",
    "vienna zoo": "Vienna",
    "moscow zoo": "Moscow",
    "henry doorly zoo": "Omaha",
    "cincinnati zoo": "Cincinnati",
    "houston zoo": "Houston",
    "dallas zoo": "Dallas",
    "atlanta zoo": "Atlanta",
    "zoo atlanta": "Atlanta",
    "oregon zoo": "Portland",
    "woodland park zoo": "Seattle",
    "lincoln park zoo": "Chicago",
    "brookfield zoo": "Chicago",
    "philadelphia zoo": "Philadelphia",
    "denver zoo": "Denver",
    "khao kheow": "Chonburi",
    "khao kheow open zoo": "Chonburi",
    "ichikawa": "Ichikawa",
    "sea world": "Orlando",
    "seaworld": "Orlando",
}

# Zoo context words required for matching
ZOO_CONTEXT_WORDS = {"zoo", "visit", "born", "born at", "at the", "safari", "aquarium", "sanctuary", "reserve"}

CITY_PATTERNS = [
    r'\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
    r'\bfrom\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
    r'\bat\s+(?:a\s+|the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:zoo|sanctuary|shelter|rescue|aquarium)',
]
CITY_PATTERNS_COMPILED = [re.compile(p) for p in CITY_PATTERNS]

# Subreddit -> location mapping for international subs
SUB_LOCATIONS = {
    "australia": "Australia",
    "unitedkingdom": "United Kingdom",
    "europe": "Europe",
    "canada": "Canada",
    "japan": "Japan",
}


def extract_location(title: str, subreddit: str) -> str | None:
    """Extract location from title or subreddit context."""
    title_lower = title.lower()

    # 1. Check zoo names (require zoo context words nearby)
    for zoo_name, location in ZOO_NAMES.items():
        if zoo_name in title_lower:
            return location

    # 2. Check for zoo-context word + city pattern
    has_zoo_context = any(w in title_lower for w in ZOO_CONTEXT_WORDS)
    if has_zoo_context:
        for pattern in CITY_PATTERNS_COMPILED:
            match = pattern.search(title)
            if match:
                city = match.group(1).strip()
                if len(city) > 2 and city.lower() not in NAME_BLACKLIST:
                    return city

    # 3. Check city patterns without zoo context
    for pattern in CITY_PATTERNS_COMPILED:
        match = pattern.search(title)
        if match:
            city = match.group(1).strip()
            if len(city) > 2 and city.lower() not in NAME_BLACKLIST:
                return city

    # 4. Subreddit location fallback for international subs
    sub_lower = subreddit.lower()
    if sub_lower in SUB_LOCATIONS:
        return SUB_LOCATIONS[sub_lower]

    return None


# --- Narrative archetypes ---
ARCHETYPES = {
    "outrage_controversy": {
        "weight": 1.3,
        "keywords": [
            "killed", "euthanized", "put down", "seized", "confiscated",
            "taken away", "stolen", "cruelty", "abuse", "abused",
            "neglect", "neglected", "torture", "tortured", "starved",
            "beaten", "shot", "poisoned", "protest", "petition",
            "outrage", "outraged", "furious", "fury", "anger",
            "justice", "injustice", "demand", "fight", "save",
            "controversy", "controversial", "banned", "illegal",
        ],
    },
    "celebrity_named": {
        "weight": 1.2,
        "keywords": [
            "named", "called", "known as", "famous", "celebrity",
            "internet famous", "viral", "beloved", "iconic", "legend",
            "legendary", "star", "mascot", "ambassador", "superstar",
            "meet", "introducing", "say hello to", "world meet",
        ],
    },
    "genetic_oddity": {
        "weight": 1.1,
        "keywords": [
            "rare", "mutation", "genetic", "albino", "melanistic",
            "leucistic", "two-headed", "two headed", "extra",
            "deformed", "deformity", "condition", "syndrome",
            "born with", "born without", "unusual", "unique",
            "one of a kind", "never seen", "first ever",
            "heterochromia", "chimera", "piebald",
        ],
    },
    "underdog_survivor": {
        "weight": 1.0,
        "keywords": [
            "rescued", "rescue", "saved", "survivor", "survived",
            "recovery", "recovering", "rehabilitation", "rehab",
            "adopted", "adoption", "foster", "shelter",
            "abandoned", "found", "lost", "stray",
            "miracle", "against all odds", "second chance",
            "before and after", "transformation", "glow up",
        ],
    },
    "unusual_behavior": {
        "weight": 1.0,
        "keywords": [
            "talks", "talking", "speaks", "speaking", "sings",
            "singing", "dances", "dancing", "plays", "playing",
            "drives", "driving", "rides", "riding", "surfs",
            "surfing", "skateboards", "skateboarding", "swims",
            "opens", "closes", "uses", "learned", "taught",
            "trained", "tricks", "trick", "genius", "smart",
            "intelligent", "clever", "figured out", "solved",
        ],
    },
    "size_anomaly": {
        "weight": 0.9,
        "keywords": [
            "biggest", "largest", "smallest", "tiniest", "giant",
            "massive", "huge", "enormous", "tiny", "miniature",
            "absolute unit", "chonk", "chonker", "thicc",
            "overweight", "obese", "fat", "chunky",
            "record", "world record", "guinness",
            "tallest", "longest", "heaviest", "lightest",
        ],
    },
    "cuteness_overload": {
        "weight": 0.8,
        "keywords": [
            "cute", "cutest", "adorable", "precious", "sweet",
            "baby", "newborn", "first time", "first day",
            "tiny", "smol", "little", "itty bitty",
            "wholesome", "heart", "heartwarming", "heartmelting",
            "aww", "omg", "squee", "cuddle", "cuddles",
            "snuggle", "snuggles", "boop", "blep", "mlem",
            "sleepy", "sleeping", "yawn", "yawning",
        ],
    },
}

# Combo bonuses (take MAX, don't stack)
COMBO_BONUSES = {
    frozenset(["outrage_controversy", "celebrity_named"]): 1.5,
    frozenset(["underdog_survivor", "cuteness_overload"]): 1.2,
    frozenset(["genetic_oddity", "size_anomaly"]): 1.15,
}


def score_narrative(title: str) -> tuple[str | None, float, list[str]]:
    """
    Score narrative archetypes for a title.
    Returns (top_archetype, narrative_score, matched_archetypes).
    Requires 2+ keywords per archetype to count.
    """
    title_lower = title.lower()
    archetype_scores = {}
    matched_archetypes = []

    for archetype, info in ARCHETYPES.items():
        matched_kw = [kw for kw in info["keywords"] if kw in title_lower]
        if len(matched_kw) >= 2:  # Minimum 2 keywords per archetype
            archetype_scores[archetype] = info["weight"]
            matched_archetypes.append(archetype)

    if not archetype_scores:
        return None, 0.0, []

    # Base score from top archetype
    top_archetype = max(archetype_scores, key=archetype_scores.get)
    base_score = archetype_scores[top_archetype]

    # Check combo bonuses (take MAX)
    combo_mult = 1.0
    for combo_set, bonus in COMBO_BONUSES.items():
        if combo_set.issubset(set(matched_archetypes)):
            combo_mult = max(combo_mult, bonus)

    narrative_score = base_score * combo_mult
    return top_archetype, narrative_score, matched_archetypes


def extract_all(title: str, subreddit: str) -> dict:
    """Run full extraction pipeline on a post title."""
    species_result = detect_species(title, subreddit)
    species = species_result[0] if species_result else None
    category = species_result[1] if species_result else None

    name = extract_name(title)
    location = extract_location(title, subreddit)
    top_archetype, narrative_score, matched_archetypes = score_narrative(title)

    return {
        "species": species,
        "category": category,
        "name": name,
        "location": location,
        "top_archetype": top_archetype,
        "narrative_score": narrative_score,
        "matched_archetypes": matched_archetypes,
    }
