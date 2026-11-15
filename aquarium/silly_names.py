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

# ---- More of everything, so names rarely repeat --------------------------------------------------------------------
FIRST_NAMES += [
    'Nigel', 'Brian', 'Carol', 'Derek', 'Elaine', 'Frank', 'Geoff', 'Hilda', 'Ian', 'Janet', 'Keith', 'Linda', 'Malcolm',
    'Nora', 'Ozzy', 'Pauline', 'Quentin', 'Rita', 'Sid', 'Trevor', 'Ursula', 'Vera', 'Wendell', 'Yvonne', 'Zed',
    'Bernard', 'Cynthia', 'Dwight', 'Edna', 'Fergus', 'Gordon', 'Harold', 'Irene', 'Jeff', 'Karen', 'Leonard', 'Marjorie',
    'Neville', 'Ophelia', 'Percy', 'Roland', 'Sandra', 'Terrence', 'Vernon', 'Winifred', 'Arthur', 'Bob', 'Chad',
    'Darlene', 'Earl', 'Florence', 'Gus', 'Herbert', 'Ingrid', 'Judith', 'Kenneth', 'Lorraine', 'Mildred', 'Ned',
    'Otis', 'Prudence', 'Reginald', 'Shirley', 'Toby', 'Ulysses', 'Velma', 'Wilbur', 'Bertha', 'Cecil', 'Dolores',
]
TITLES += [
    'the Magnificent', 'the Slightly Damp', 'Mouth', 'the Aggressive Mouth', 'Lord of the Rockwork', 'the Hungry',
    'Pellet Hoover', 'the Unbothered', 'Snack Time', 'the Overflow Explorer', 'the Rockscaper', 'Lights Out',
    'the Nitrate Whisperer', 'Five Seconds', 'the Ich Survivor', 'the Glass Kisser', 'Wet Socks', 'the Midnight Snacker',
    'the Filter Sock Bandit', 'Probably Fine', 'the Sump Escapee', 'the Coral Critic', 'Shy Guy', 'the Drama Queen',
    'the Bottom Feeder', 'the Influencer', 'the Retiree', 'the Very Expensive', 'Free With Purchase', 'the Hitchhiker',
    'the Night Shift', 'Zero Chill', 'the Professional', 'the Menace', 'the Unpaid Intern', 'the Algae Intern',
    'Big Tuna', 'the Moneypit', 'the Tank Boss', 'Wiggles',
]
for kind, extra in {
    'snail': ['Crawlsworth', 'McSlime', 'Shellby', 'Gastropodolous', 'Slimeington', 'Turbocharger', 'Algaegobbler'],
    'crab': ['Shellswapper', 'Clawford', 'Crabbington', 'McNipper', 'Pinchwhistle', 'Shellsby'],
    'shrimp': ['Flickerton', 'Shrimpkins', 'McWhisker', 'Molterson', 'Scampi', 'Dancefloor'],
    'urchin': ['Spinington', 'McNeedle', 'Hedgehogson', 'Glueface'],
    'star': ['Armsworth', 'Fivesy', 'Starfield', 'McLimb'],
    'coral': ['Polypington', 'McCalcium', 'Skeletonsworth', 'Glowsworth', 'Reefington', 'Stony'],
    'anemone': ['Wanderworth', 'McSting', 'Splitsworth', 'Hostalot'],
    'clown': ['Nemoington', 'McHost', 'Clownsworth', 'Wobbleton', 'Anemoneless'],
    'tang': ['Grazington', 'McAlgae', 'Tangerine', 'Swimfast', 'Ichsworth'],
    'goby': ['Hoverworth', 'McBurrow', 'Pistolpal', 'Peekaboo'],
    'blenny': ['Bigeyes', 'McPerch', 'Lookalot', 'Grumbleton'],
    'wrasse': ['Jumpsworth', 'Zippington', 'McCarpet', 'Lidchecker'],
    'fish': ['Swimsworth', 'McGill', 'Flapperton', 'Sushington', 'Brineworth', 'Bubbleworth', 'Snackwell',
             'Finnegan', 'Scalington', 'Pellington', 'Mouthsworth', 'Fishburne', 'Gulperton', 'McSplash'],
}.items():
    SURNAMES[kind] += extra
SOLO_NAMES += [
    'Admiral Ackbar Jr.', 'Chairman of the Board', 'Snack', 'Lunch', 'Mr. Wiggles', 'Big Gary', 'Small Gary',
    'Captain Salinity', 'The Duke of Detritus', 'Countess Copepod', 'Agent Ammonia', 'Professor Phosphate',
    'Lord Lumen', 'The Night Manager', 'Sir Scrubsalot', 'Madame Mysis', 'Sheriff Skimmer', 'Judge Judy Jr.',
    'Wet Kevin', 'The Intern', 'Budget Line Item', 'Refund Pending', 'Insurance Claim', 'The Usual Suspect',
    'Baby Shark (Not A Shark)', 'Your Majesty', 'Pickles', 'Meatball', 'Noodle', 'Toast',
]
HONORIFICS = ['Sir', 'Lady', 'Lord', 'Dame', 'Captain', 'Dr.', 'Professor', 'Admiral', 'Baron', 'Duchess',
              'Sergeant', 'Reverend', 'Detective', 'Chef', 'Coach', 'Grand Duke', 'His Excellency', 'Her Majesty']
ORDINALS = ['Jr.', 'Sr.', 'the 2nd', 'the 3rd', 'the 4th', 'the 5th', 'the 11th', 'the 47th', 'Esq.', 'PhD',
            'the Last', 'the Even Younger']

# Read out whenever a name is rolled. {kind} is the animal's own common name, {name} its new one.
ANNOUNCEMENTS = [
    'By royal decree, this {kind} shall henceforth be known as {name}.',
    'Hear ye, hear ye! The {kind} formerly known as nobody is now {name}.',
    'After a lengthy court case, the {kind} has legally changed its name to {name}.',
    'The council of elder snails has spoken: this {kind} is {name}.',
    'Breaking news: local {kind} identifies as {name}. Neighbours "not surprised".',
    'The {kind} has been knighted. Arise, {name}.',
    'Paperwork filed in triplicate. This {kind} is officially {name}.',
    'The {kind} looked at the glass, thought about it, and decided it is {name}.',
    'Congratulations! It\'s a {name}.',
    'Your {kind} has accepted the name {name}, and requests extra mysis to celebrate.',
    'Witness protection has relocated this {kind}. It now goes by {name}.',
    'The tank has voted (the cleanup crew abstained). Welcome, {name}.',
    'A name fit for a {kind}: {name}. Please bow when passing the glass.',
    'Name tag printed, laminated and stuck to the glass: {name}.',
    'The {kind} filled in the form itself. It insists on {name}.',
    'From this day forth, let it be written in the parameter log: {name}.',
    'Scientists confirm this {kind} has always been {name}. We just didn\'t know.',
    'The {kind} answers to {name} now. It answers to food faster.',
    'A star is born. Ladies and gentlemen, {name}!',
    'The {kind} is thrilled to be {name}. It\'s hard to tell, but it is.',
    'Sponsored by the sump: this {kind} is now {name}.',
    'New phone, who dis? It\'s {name}, formerly a {kind} with no name.',
    'Christened with a single drop of RO/DI: {name}.',
    'Introducing the one, the only, the slightly damp {name}.',
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
    if style < 0.3:
        return f'{first} "{random.choice(TITLES)}" {surname}'
    if style < 0.5:
        return f'{random.choice(HONORIFICS)} {first} {surname} {random.choice(ORDINALS)}'
    if style < 0.65:
        return f'{random.choice(HONORIFICS)} {first} "{random.choice(TITLES)}" {surname}'
    if style < 0.8:
        return f'{first} {surname}'
    if style < 0.9:
        return f'{first} {random.choice(TITLES)}'
    return random.choice(SOLO_NAMES)


def name_count(about=''):
    """Roughly how many different names silly_name can give this kind of animal."""
    firsts, titles, surnames = len(FIRST_NAMES), len(TITLES), len(SURNAMES[kind_of(about)])
    honorifics, ordinals = len(HONORIFICS), len(ORDINALS)
    return (firsts * titles * surnames + honorifics * firsts * surnames * ordinals
            + honorifics * firsts * titles * surnames + firsts * surnames + firsts * titles + len(SOLO_NAMES))


def announcement(kind, name):
    """The fanfare when a name is given. `kind` is the animal's common name, such as 'Royal Gramma'."""
    kind = (kind or '').strip() or 'critter'
    return random.choice(ANNOUNCEMENTS).format(kind=kind, name=name)


def random_epitaph(not_this=''):
    """A line for the tombstone. {date} stays in it and becomes the date of death when shown."""
    return random.choice([line for line in EPITAPHS if line != not_this])
