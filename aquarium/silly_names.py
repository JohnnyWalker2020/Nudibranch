"""Silly names for livestock, and what gets carved on their tombstones. Plain Python, so models can import it."""
import random

FIRST_NAMES = [
    'Jim', 'Timothy', 'Gerald', 'Doris', 'Kevin', 'Brenda', 'Walter', 'Agnes', 'Norman', 'Mabel', 'Stanley', 'Phyllis',
    'Barry', 'Gladys', 'Clive', 'Maureen', 'Dennis', 'Ethel', 'Hank', 'Beatrice', 'Morris', 'Wanda', 'Rupert', 'Tina',
    'Lloyd', 'Pam', 'Vince', 'Olive', 'Duane', 'Sheila',
]
TITLES = [
    'the Bruiser', 'the Unready', 'Two Fins', 'Big Gulp', 'the Vacuum', 'No Regrets', 'the Lurker', 'Quick Fins',
    'the Landlord', 'Mostly Harmless', 'the Algae Baron', 'Sideways', 'the Accountant', 'Bad News', 'the Nibbler',
    'Glass Surfer', 'the Mortician', 'Three Meals', 'the Rock Wrecker', 'Tiny Hands',
]
# Surnames by the kind of animal, found from words in its common or Latin name.
SURNAMES = {
    'snail': ['Snailson', 'Slowpoke', 'McShell', 'Trundleton', 'Glasslicker'],
    'crab': ['Crabtree', 'Sideways', 'Pinchley', 'McClaw', 'Scuttleworth'],
    'shrimp': ['Shrimpton', 'Prawnsby', 'Featherlegs', 'Antennae', 'Cleanerton'],
    'urchin': ['Spikesworth', 'Pincushion', 'McPrickle', 'Rockroller'],
    'star': ['Fivelegs', 'Starbuckle', 'Armstrong', 'Sandsifter'],
    'coral': ['Polypson', 'Fragsworth', 'McBranch', 'Stayput', 'Stingley'],
    'anemone': ['Wanderley', 'Tentacleton', 'Stingley', 'Roamsworth'],
    'clown': ['Hostwiggle', 'McSquirt', 'Wigglesworth', 'Anemonesitter'],
    'tang': ['Tangsworth', 'Scalpelton', 'Lawnmower', 'McGrazer'],
    'goby': ['Sandsifter', 'Burrowman', 'Hoverton', 'Rockwatcher'],
    'blenny': ['Glassfacer', 'Perchley', 'McGrumpface', 'Scrapington'],
    'wrasse': ['Sandsleeper', 'Zipperton', 'McFlash', 'Podhunter'],
    'fish': ['Tailspot', 'McFlipper', 'Finley', 'Bubbleton', 'Gillespie', 'Scalesworth', 'Pelletwhistle', 'Fintastic'],
}
KIND_WORDS = [
    ('snail', ('snail', 'nassarius', 'turbo', 'trochus', 'cerith', 'conch', 'astrea', 'nerite')),
    ('crab', ('crab', 'hermit')),
    ('shrimp', ('shrimp', 'prawn', 'lysmata', 'peppermint')),
    ('urchin', ('urchin',)),
    ('star', ('starfish', 'star', 'serpent')),
    ('anemone', ('anemone', 'entacmaea')),
    ('coral', ('coral', 'zoa', 'acropora', 'montipora', 'euphyllia', 'hammer', 'torch', 'frogspawn', 'mushroom', 'leather',
               'sps', 'lps', 'palythoa', 'frag', 'gorgonian', 'clam')),
    ('clown', ('clown', 'amphiprion')),
    ('tang', ('tang', 'surgeon', 'zebrasoma', 'acanthurus', 'paracanthurus')),
    ('goby', ('goby', 'gobiodon', 'firefish', 'dartfish')),
    ('blenny', ('blenny',)),
    ('wrasse', ('wrasse',)),
]
SOLO_NAMES = [
    'Professor Bubbles', 'Sir Reginald Finsworth III', 'Kevin', 'Steve', 'Sergeant Salt', 'Lady Algae', 'Tax Write-Off',
    'Captain Overflow', 'Gary From Accounting', 'Princess Pellet', 'The Water Change', 'Detritus Dave', 'Nitrate Nancy',
    'Skimmer Pete', 'Old Man Protein', 'Mister Mysis', 'Dr. Salinity', 'Baron von Refugium', 'Biofilm Barbara', 'Doug',
]

EPITAPHS = [
    'Flushed on {date}.',
    'Floating right side up in our hearts.',
    'Went belly up on {date}. Never forgotten, rarely fed on time.',
    'Swam toward the light. It was the refugium light.',
    'Gone to the big sump in the sky.',
    'Now feeding the copepods.',
    'Beloved by many. Nibbled by some.',
    'The lid was right there.',
    'Lost a fight with the overflow on {date}.',
    'Last seen heading into the rockwork on {date}.',
    'Parameters were stable. Sadly, they were not.',
    'Burial at sea, by way of the toilet, {date}.',
    'Reached the great skimmer cup in the sky.',
    'One last water change: {date}.',
    'Gone, but still showing up on the nitrate test.',
    'Not hiding this time. We checked.',
    'Not sleeping this time. We checked twice.',
    'Returned to the bioload on {date}.',
    'Thought the powerhead looked friendly.',
    'Survived the cycle. Did not survive {date}.',
    'Quarantined forever, effective {date}.',
    'Paid in full. Enjoyed for about a week.',
    'Off to the Great Barrier in the sky.',
    'Sank peacefully on {date}, to the delight of the hermit crabs.',
    'Salinity was perfect. Timing was not.',
    'Requested a transfer to the porcelain reef, {date}.',
]


def kind_of(text):
    """Which set of surnames suits an animal, from its common or Latin name."""
    text = (text or '').lower()
    for kind, words in KIND_WORDS:
        if any(word in text for word in words):
            return kind
    return 'fish'


def silly_name(about=''):
    """A saved-forever name. `about` is the animal's common or Latin name, so a snail can be a Snailson."""
    first = random.choice(FIRST_NAMES)
    surname = random.choice(SURNAMES[kind_of(about)])
    style = random.random()
    if style < 0.4:
        return f'{first} "{random.choice(TITLES)}" {surname}'
    if style < 0.75:
        return f'{first} {surname}'
    return random.choice(SOLO_NAMES)


def random_epitaph(not_this=''):
    """A line for the tombstone. {date} stays in it and becomes the date of death when shown."""
    return random.choice([line for line in EPITAPHS if line != not_this])
