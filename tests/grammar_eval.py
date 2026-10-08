"""Score the grammar prompt on real sentences (calls the CLI, so not run by pytest).

Usage: python tests/grammar_eval.py old [runs]       the prompt in grammar.py
       python tests/grammar_eval.py new [runs] FILE  a candidate prompt from FILE

8 Oct 2026, this prompt with two passes: caught 10/10, false alarms 0/6.
"""
import sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from mr_tharoor import grammar

# (text, words that must appear in some should_be, or None = must not be marked at all)
CASES = [
    ("does macos accessibility feature is working or not can you prove it", ["is the"]),
    ("can you see that now i have gave the permission for typing", ["given"]),
    ("one of my friend told me about this company last week", ["friends"]),
    ("can you built the macos accessibility feature and make it safe", ["build"]),
    ("when i am typing in gmail so does python mic will be on", ["will the"]),
    ("i has finished the work yesterday and it were good", ["was"]),
    ("but how does it is able to calculate the cost of the token", ["is it"]),
    ("can you tell me how many tokens is burned in claude code", ["are"]),
    ("we are excited and happy to announce of it today", ["announce it"]),
    ("he don't know where the files are stored on the laptop", ["doesn't"]),
    ("Hi this side baibhav and i am thinking of building an AI company from bihar", None),
    ("I want to make a company for farmers in bihar after college", None),
    ("you need to clear my doubts about the pricing before friday", None),
    ("please do the needful and prepone the meeting to monday", None),
    ("can you check that everything is working or not on my mac", None),
    ("I am out of station this week so we can talk on monday", None),
]

def run():
    items = [(f"c{i}", t) for i, (t, _) in enumerate(CASES)]
    found = grammar.llm_check(items, "typed")
    by = {}
    for f in found:
        by.setdefault(f.source, []).append(f)
    caught = missed = false_alarm = 0
    for i, (text, want) in enumerate(CASES):
        got = by.get(f"c{i}", [])
        shown = "; ".join(f"{f.said} -> {f.should_be}" for f in got)
        if want is None:
            ok = not got; false_alarm += bool(got)
        else:
            ok = any(any(w in f.should_be.lower() for w in want) for f in got)
            caught += ok; missed += not ok
        print(f"  {'ok ' if ok else 'BAD'} {text[:55]:55} | {shown}")
    errors = sum(w is not None for _, w in CASES)
    print(f"  caught {caught}/{errors}, false alarms {false_alarm}/{len(CASES) - errors}")
    return caught, false_alarm

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "new":
        grammar.PROMPT = open(sys.argv[3] if len(sys.argv) > 3 else __file__.replace("gram_eval.py", "prompt_new.txt")).read()
    for r in range(int(sys.argv[2]) if len(sys.argv) > 2 else 2):
        t = time.time(); print(f"run {r + 1}"); run(); print(f"  {time.time() - t:.0f}s")
