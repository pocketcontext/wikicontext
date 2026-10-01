# Full-corpus semantic search CLI experiment

This experiment asks OpenAI to rank pages from one immutable WikiContext
publication. It does not change the application server, browser UI, publication
pipeline or search index. Sources and generated Obsidian files are not inputs.

`prepare` reads WikiContext and stores a private local snapshot. `search` and
`benchmark` send that snapshot and the query to OpenAI and incur API charges.
They return ranked pages with excerpts selected from the stored canonical text,
not generated answers or evidence citations. Relevance is not guaranteed.

## Install and authenticate

From the WikiContext repository, create a virtual environment outside Git:

```sh
python3 -m venv "$HOME/.cache/wikicontext-search-poc-venv"
"$HOME/.cache/wikicontext-search-poc-venv/bin/python" -m pip install -r tools/semantic_search_poc/requirements.txt
source "$HOME/.cache/wikicontext-search-poc-venv/bin/activate"
export WIKICONTEXT_URL=https://wiki.pocketcontext.com
export WIKICONTEXT_USER_EMAIL=you@pocketcontext.com
python skills/wikicontext/scripts/wc.py login --google
```

If Python's venv/ensurepip module is unavailable, install the operating system's
venv package or use `uv venv` and `uv pip install` with the same environment path.
Load `OPENAI_API_KEY` securely from your environment before model requests.
Never put the key in an argument, query file, benchmark report or repository.

## Try a search

```sh
python tools/semantic_search_poc/cli.py prepare
python tools/semantic_search_poc/cli.py count
python tools/semantic_search_poc/cli.py search 'vector databases' --baseline
python tools/semantic_search_poc/cli.py search 'vector databases' --json
```

Preparation pins the latest complete publication by default. Re-run preparation
to adopt new publications. Use `prepare --publication ID` or `prepare --sequence
N` for history. Search links remain pinned to the prepared publication.

`count` sends the exact request content to OpenAI's input-token counter without
generating search results. This requires the API key and uploads the corpus.
It is more accurate than a character-based token estimate. The request uses
compact arrays with declared field names to reduce overhead without summarizing
or dropping page text. Context-window capacity and account throughput limits
are separate: the full request must fit both.

Cached content is private company data. The default cache is outside Git in the
user's XDG cache directory; directories are private and files use mode 0600.
Fresh authentication gates searches, but revoking an account cannot erase its
existing local copies. Delete the experiment's cache when it is no longer needed.

## Compare results

Copy `queries.example.json` to a private location and adapt it to your corpus.
Its questions and expected slugs are synthetic examples, not known wiki content.

```sh
python tools/semantic_search_poc/cli.py benchmark /private/queries.json --models gpt-6-luna --repeat 3 --interval 65 --baseline --json
```

Compare `gpt-6-luna` and `gpt-6.1-sol` explicitly when the additional metered calls
are useful: `--models gpt-6-luna gpt-6.1-sol`. Luna uses no reasoning; Sol uses low reasoning. The experiment does
not automatically escalate models or retry OpenAI requests. Keep output reports
private because they may contain queries, excerpts and links. A failed run stops
the benchmark with a nonzero exit code and a partial report preserving completed
runs and any returned usage; a timeout can still be billed without reported usage.
`--interval` deliberately spaces successive searches; it is not a retry policy.
Choose it for your account's tokens-per-minute allowance. Cached input still
counts toward that allowance. Safe error reports include rate-limit codes and
allowlisted limit/reset headers, never provider response messages.

Judge relevance with expected page slugs and inspect the excerpts yourself.
Include exact names, paraphrases, obscure details and no-answer questions.
Compare against publication-scoped FTS with the CLI's baseline option. FTS uses
literal AND token matching, so natural-language questions can have no matches.
Absence of expected labels means relevance is unscored, not a failure. An explicit
empty `expected_slugs` list labels a no-answer question.

Measure repeated calls rather than assuming a warm cache. A stable instruction
message and corpus precede the variable query. OpenAI cache lifetime and routing
can still cause misses. Reported model-call latency excludes preparation and
must not be presented as browser latency. The report includes API and CLI timings,
plus separate FTS timing when requested. Original excerpts are bounded for display;
the corpus sent to the model is not truncated. Cost is an estimate from returned
usage and versioned Standard rates; it is not an invoice or a spend limit.
Prompts above 272,000 input tokens have different rates. Unknown usage must not
be interpreted as free. Paragraph identifiers and JSON formatting add tokens
beyond a simple character-based estimate of the wiki text.

## Validation

```sh
python3 tests/semantic_search_poc.py
```

Tests use synthetic data and mocked providers; they incur no OpenAI charges.
The application README lists the broader isolated backend validation commands.

API references: [Responses](https://developers.openai.com/api/docs/guides/responses),
[prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching),
[pricing](https://developers.openai.com/api/docs/pricing), and
[data controls](https://developers.openai.com/api/docs/guides/your-data).
The client requests `store: false`; provider abuse-monitoring and prompt-cache
retention are separate controls. No tools or provider file/vector stores are used.
