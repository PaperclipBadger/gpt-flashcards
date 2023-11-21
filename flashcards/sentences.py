import asyncio
import dataclasses
import functools
import itertools
import pathlib
import re
import sqlite3

import openai
import yaml


DATABASE = pathlib.Path("sentences.db")
CONFIG = pathlib.Path("config.yaml")


class RateLimiter:
    def __init__(self, rpm: int) -> None:
        self.sem = asyncio.Semaphore(rpm)
        self.rpm = rpm
        self.sleepers = set()
    
    def sleeper_callback(self, task):
        self.sleepers.remove(task)
        self.sem.release()

    async def __aenter__(self):
        await self.sem.acquire()
        task = asyncio.create_task(asyncio.sleep(60))
        self.sleepers.add(task)
        assert len(self.sleepers) <= self.rpm
        task.add_done_callback(self.sleeper_callback)
    
    async def __aexit__(self, exc_type, exc, tb):
        pass


def init_cache() -> None:
    DATABASE.touch()
    with sqlite3.connect(DATABASE) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT
            );

            CREATE TABLE IF NOT EXISTS sentences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word INTEGER,
                sentence TEXT,
                FOREIGN KEY(word) REFERENCES words(id)
            );
            """
        )


def encache_sentences(word: str, sentences: list[str]) -> None:
    if not DATABASE.exists():
        init_cache()

    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.execute("SELECT id FROM words WHERE word = ?", (word,))
        if not (row := cursor.fetchone()):
            conn.execute("INSERT INTO words (word) VALUES (?)", (word,))
            cursor = conn.execute("SELECT id FROM words WHERE word = ?", (word,))
            row = cursor.fetchone()
        
        word_id, = row

        for sentence in sentences:
            conn.execute("INSERT INTO sentences (word, sentence) VALUES (?,?)", (word_id, sentence))


def decache_sentences(word: str) -> list[str]:
    if not DATABASE.exists():
        init_cache()
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.execute(
            """
            SELECT sentences.sentence 
            FROM words 
            LEFT JOIN sentences ON words.id = sentences.word
            WHERE words.word = ?
            """,
            (word,),
        )
        return [row[0] for row in cursor.fetchall() if row[0]]


@dataclasses.dataclass(frozen=True)
class Cloze:
    context: list[str]
    deletions: list[str]

    @classmethod
    def from_str(cls, s: str) -> "Cloze":
        context = []
        deletions = []

        i = 0

        for match in re.finditer(r"\[(.*?)\]", s):
            context.append(s[i:match.start()])
            deletions.append(match.group(1))
            i = match.end()
        
        context.append(s[i:])

        return cls(context, deletions)

    def fill(self, *values: str) -> str:
        if not values:
            values = ("[...]",)

        wrapped = ["<b>" + value + "</b>" for value in values]
        parts = itertools.chain.from_iterable(zip(self.context, itertools.cycle(wrapped)))
        return "".join(list(parts)[:2 * len(self.context) - 1])

    @functools.cached_property
    def cloze(self) -> str:
        return self.fill()
    
    @functools.cached_property
    def sentence(self) -> str:
        return self.fill(*self.deletions)


client = None
config = None


def init_client():
    global config, client

    if config is None:
        with open(CONFIG) as f:
            config = yaml.safe_load(f)
    
    if client is None:
        client = openai.AsyncOpenAI(api_key=config["openai"]["api_key"])


completion_rate_limiter = RateLimiter(499)


async def query_gpt(word: str) -> list[str]:
    if (cached_sentences := decache_sentences(word)):
        return cached_sentences
    
    init_client()
    
    async with completion_rate_limiter:
        completion = await client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=[
                dict(role="system", content=config["openai"]["system_prompt"]),
                dict(role="user", content=word),
            ],
        )

    response = completion.choices[0].message.content.strip()

    sentences = []

    for candidate in response.split("\n\n"):
        if (match := re.match(r"^\d+\. (.*?\n.*?)$", candidate)):
            sentences.append(match.group(1))

    encache_sentences(word, sentences)

    return sentences


async def example_sentences(word: str) -> list[tuple[Cloze, Cloze]]:
    sentences = await query_gpt(word)

    examples = []
    for pair in sentences:
        sentence, translation = pair.split("\n")
        examples.append((Cloze.from_str(sentence), Cloze.from_str(translation)))

    return examples


count = iter(itertools.count())
tts_rate_limiter = RateLimiter(49)


async def tts(sentence: str, path: pathlib.Path) -> None:
    if path.exists():
        return

    # drop any html formatting from sentence
    sentence = re.sub(r"</?\w+>", "", sentence)

    if not sentence:
        raise Exception("lolwut")

    init_client()

    voice = ["alloy", "echo", "fable", "onyx", "nova"][next(count) % 5]

    async with tts_rate_limiter:
        response = await client.audio.speech.create(
            # tts-1-hd is twice as expensive for no noticeable improvement (in Polish).
            model="tts-1",
            voice=voice,
            input=sentence,
            response_format="mp3",
        )
    response.stream_to_file(path)