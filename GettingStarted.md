# Getting Started: Test Locally & Submit

This guide walks you through building an agent, testing it locally, and submitting it to this simulation competition.

## Test Locally

Install the environment from PyPI (any recent release that includes Kaggriculture):

```bash
pip install -U kaggle-environments
```

Run a game from Python or a notebook — you can pass agent functions directly, or paths to `.py` files:

```python
from kaggle_environments import make

env = make("kaggriculture", configuration={"episodeSteps": 720}, debug=True)
env.run([agent, "random"])  # or env.run(["main.py", "random"]) to load from a file

# View result
final = env.steps[-1]
for i, s in enumerate(final):
    print(f"Player {i}: reward={s.reward}, status={s.status}")

# Render in a notebook
env.render(mode="ipython", width=1200, height=800)

# Or dump a replay JSON for the visualizer / offline analysis
import json
with open("replay.json", "w") as f:
    json.dump(env.toJSON(), f)
```

Three built-in agents are available by name: `"pass"`, `"random"`, and `"starter"` (a deterministic baseline).

## Set Up the Kaggle CLI

Install the CLI:

```bash
pip install kaggle
```

You'll need a Kaggle account — sign up at <https://www.kaggle.com> if you don't have one. Then download your API credentials at <https://www.kaggle.com/settings/api> by clicking "Generate New Token" under the "API" section.

**Recommended: API token file.** Save the token string to `~/.kaggle/access_token`:

```bash
mkdir -p ~/.kaggle
# Paste the token from the Kaggle settings UI into this file
nano ~/.kaggle/access_token
chmod 600 ~/.kaggle/access_token
```

Alternative auth methods:

- OAuth (browser flow): `kaggle auth login`
- Environment variable: `export KAGGLE_API_TOKEN=xxxxxxxxxxxxxx`

Verify the CLI is wired up:

```bash
kaggle competitions list -s "kaggriculture"
```

## Find the Competition

```bash
kaggle competitions list -s "kaggriculture"
kaggle competitions pages kaggriculture
kaggle competitions pages kaggriculture --content
```

## Accept the Competition Rules

Before submitting, you must accept the rules on the Kaggle website. Navigate to <https://www.kaggle.com/competitions/kaggriculture> and click "Join Competition".

Verify you've joined:

```bash
kaggle competitions list --group entered
```

## Download Competition Data

```bash
kaggle competitions download kaggriculture -p kaggriculture-data
```

## Submit Your Agent

Your submission must have a `main.py` at the root with an `agent` function.

Single file agent:

```bash
kaggle competitions submit kaggriculture -f main.py -m "Wheat loop v1"
```

Multi-file agent — bundle into a `tar.gz` with `main.py` at the root:

```bash
tar -czf submission.tar.gz main.py helper.py model_weights.pkl
kaggle competitions submit kaggriculture -f submission.tar.gz -m "Multi-file agent v1"
```

Notebook submission:

```bash
kaggle competitions submit kaggriculture -k YOUR_USERNAME/kaggriculture-agent -f submission.tar.gz -v 1 -m "Notebook agent v1"
```

## Monitor Your Submission

Check submission status:

```bash
kaggle competitions submissions kaggriculture
```

Note the submission ID from the output — you'll need it for episodes.

## List Episodes

Once your submission has played some games:

```bash
kaggle competitions episodes <SUBMISSION_ID>
```

CSV output for scripting:

```bash
kaggle competitions episodes <SUBMISSION_ID> -v
```

## Download Replays and Logs

Download the replay JSON for an episode (for visualization or analysis):

```bash
kaggle competitions replay <EPISODE_ID>
kaggle competitions replay <EPISODE_ID> -p ./replays
```

Download agent logs to debug your agent's behavior:

```bash
# Logs for the first agent (index 0)
kaggle competitions logs <EPISODE_ID> 0

# Logs for the second agent (index 1)
kaggle competitions logs <EPISODE_ID> 1 -p ./logs
```

## Check the Leaderboard

```bash
kaggle competitions leaderboard kaggriculture -s
```

## Typical Workflow

```bash
# Test locally
python -c "
from kaggle_environments import make
env = make('kaggriculture', debug=True)
env.run(['main.py', 'random'])
print([(i, s.reward) for i, s in enumerate(env.steps[-1])])
"

# Submit
kaggle competitions submit kaggriculture -f main.py -m "v1"

# Check status
kaggle competitions submissions kaggriculture

# Review episodes
kaggle competitions episodes <SUBMISSION_ID>

# Download replay and logs
kaggle competitions replay <EPISODE_ID>
kaggle competitions logs <EPISODE_ID> 0

# Check leaderboard
kaggle competitions leaderboard kaggriculture -s
```
