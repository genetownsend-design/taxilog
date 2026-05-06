# From Idea to Cloud: A Beginner's Guide to Building and Deploying a Web App

This guide walks through the full lifecycle of a small web application — from the first idea to a live URL anyone can visit. It is written for people who are comfortable using a computer but new to software development.

---

## Part 1: Planning

### Start with the problem, not the solution

Before writing a single line of code, write down in plain English what problem the app solves. Be specific.

**Bad:** "I want an app to track stuff."  
**Good:** "I want to log each taxi pickup during my shift — where I picked them up, the fare, and how I got paid — so I can see my earnings at the end of the day without keeping paper notes."

That second version tells you almost everything you need to know to build the app.

### Write user stories

A user story is a one-sentence description of something the app's user needs to do. Format: *"As a [who], I want to [what], so that [why]."*

Examples:
- As a driver, I want to add a new pickup with fare details, so I can record it while it's fresh.
- As a driver, I want to see a daily total of my earnings, so I know what I made today.
- As a driver, I want to export my records as a PDF, so I can hand something to my accountant.

User stories become your feature list. If a feature doesn't map to a user story, question whether you need it.

### Decide what data you need to store

Every app stores information. List the things your app needs to remember.

For a pickup log, that list is:
- Pickups (date, pickup location, meter amount, tip, payment type)
- Customer names (for regular passengers)
- Driver profile (name, pay rate structure)
- Expenses (fuel, tolls, etc.)
- Shift records (start time, end time, notes)

Each item in that list becomes a **data file** or a **database table**. For a small personal app, simple JSON files work fine. For an app serving thousands of users, you'd use a proper database.

### Choose a tech stack

A "tech stack" is the combination of tools and languages you'll use. For a beginner building a small web app, this combination is practical and well-documented:

| Layer | Choice | What it does |
|---|---|---|
| Language | Python | Runs on the server, handles data |
| Web framework | FastAPI | Handles HTTP requests, serves pages |
| Templates | Jinja2 | Fills HTML pages with live data |
| Frontend | HTML + CSS + JavaScript | What the user sees in the browser |
| Storage | JSON files (local) / Cloud bucket (deployed) | Saves data between sessions |
| Hosting | Google Cloud Run | Serves the app at a public URL |

Don't chase the newest or most impressive tools. Choose tools with good documentation and large communities — you'll spend a lot of time reading answers on Stack Overflow.

### Sketch the screens

Before writing code, sketch every screen the user will see. Paper and pencil is fine. Each sketch should show:
- What information is displayed
- What buttons or forms are available
- What happens when the user clicks something

Common screens for a data-entry app:
- **List view** — shows all records, with add/edit/delete controls
- **Detail / form view** — add or edit a single record
- **Summary / report view** — totals, charts, exports

---

## Part 2: Setting Up

### Install the tools

You need three things on your computer before you can start:

1. **Python 3.10+** — download from python.org
2. **A code editor** — VS Code is free and beginner-friendly
3. **A terminal** — Terminal on Mac, Command Prompt or PowerShell on Windows, or any Linux terminal

### Create a project folder

```bash
mkdir my-app
cd my-app
```

Everything for your app lives in this folder.

### Create a virtual environment

A virtual environment keeps your app's Python packages separate from everything else on your computer.

```bash
python3 -m venv venv
source venv/bin/activate    # Mac/Linux
venv\Scripts\activate       # Windows
```

You'll see `(venv)` in your prompt when it's active. Always activate it before working on the project.

### Install dependencies

Create a file called `requirements.txt` listing the packages your app needs:

```
fastapi==0.104.1
uvicorn[standard]
jinja2==3.1.4
python-multipart
aiofiles
```

Install them all at once:

```bash
pip install -r requirements.txt
```

---

## Part 3: Building the App

### Structure of a FastAPI app

FastAPI apps have a clear pattern. Every page or action maps to a Python function called a **route handler**.

```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def home():
    return "<h1>Hello</h1>"
```

Run it:

```bash
python3 main.py
```

Open `http://localhost:8000` in your browser and you'll see your page.

### The request/response cycle

Every interaction in a web app follows this pattern:

1. User does something in the browser (loads a page, clicks a button, submits a form)
2. Browser sends an **HTTP request** to the server
3. Server runs the matching route handler
4. Server sends back an **HTTP response** (an HTML page, JSON data, a file, etc.)
5. Browser displays the result

Understanding this cycle is the single most important concept in web development.

### Separate reads from writes

Use two HTTP methods:
- **GET** — read data, display a page. Safe to repeat. No side effects.
- **POST** — create or change data. Has side effects (saves something, deletes something).

```python
@app.get("/pickups")          # show the list
def list_pickups(): ...

@app.post("/pickups")         # save a new pickup
def add_pickup(data: ...): ...

@app.delete("/pickups/{id}")  # remove one
def delete_pickup(id: str): ...
```

### Build the data layer first

Before building any UI, write the functions that read and write your data files. Test them in isolation. If your data layer is solid, the rest of the app is just plumbing.

```python
import json
from pathlib import Path

DATA_FILE = Path("data/pickups.json")

def read_pickups():
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE) as f:
        return json.load(f)

def write_pickups(records):
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(records, f, indent=2)
```

### Build one feature at a time

Don't try to build everything at once. Pick the single most important feature, build it end-to-end (data → server → UI), and confirm it works before moving to the next.

Order of priority: get the core data loop working first (add a record, see it in the list, delete it). Everything else — reports, exports, settings — comes after.

### Test as you go

After every meaningful change, open the browser and use the feature. Don't wait until the whole app is done to find out something is broken. Bugs caught immediately take minutes to fix; bugs caught later can take hours.

---

## Part 4: Version Control with Git

Version control is a system that records every change you make to your code. It lets you go back to any earlier state, see what changed and when, and work on multiple versions simultaneously.

### Initialize a repository

```bash
git init
git add main.py requirements.txt
git commit -m "Initial commit"
```

### Commit often

A commit is a named snapshot of your code. Commit whenever you finish something meaningful — not every line, but not once a week either. Good commit messages describe *why* you made a change, not *what* the code does.

```bash
git add main.py
git commit -m "Add delete pickup endpoint with proper 404 handling"
```

### Tag important milestones

When you reach a known-good state you might want to return to, tag it:

```bash
git tag v1.0 -m "Working local version before cloud migration"
```

### Push to GitHub

GitHub is a website that stores your git repository online — a backup and a collaboration tool.

```bash
# One-time setup
git remote add origin https://github.com/yourusername/your-repo.git
git push -u origin master

# Every subsequent push
git push
```

---

## Part 5: Preparing for Deployment

### Why local and deployed are different

On your own computer, data files stay between runs. On a cloud server, containers are **ephemeral** — they can be restarted or replaced at any time, wiping anything stored locally inside them.

The solution: store data in a separate, persistent service. On Google Cloud, that's **Cloud Storage (GCS)**. On AWS, it's **S3**. Both are simple key-value blob stores — you write a file by name, read it back by name.

### Abstract your storage early

Write your data read/write functions so they can swap between local files and cloud storage based on an environment variable. This means you can develop locally (fast, no cloud costs) and deploy to the cloud without changing any other code.

```python
import os, json
from pathlib import Path

GCS_BUCKET = os.environ.get("GCS_BUCKET")  # set in cloud, absent locally

def read_data(filename):
    if GCS_BUCKET:
        # read from cloud
        from google.cloud import storage
        blob = storage.Client().bucket(GCS_BUCKET).blob(filename)
        return json.loads(blob.download_as_text()) if blob.exists() else []
    # read from local file
    p = Path("data") / filename
    return json.loads(p.read_text()) if p.exists() else []

def write_data(filename, data):
    if GCS_BUCKET:
        from google.cloud import storage
        blob = storage.Client().bucket(GCS_BUCKET).blob(filename)
        blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")
        return
    p = Path("data") / filename
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(data, indent=2))
```

### Containerize with Docker

A container packages your app and all its dependencies into a single, self-contained unit that runs identically everywhere — your laptop, a test server, or a cloud provider.

Create a file called `Dockerfile` in your project folder:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
ENV PORT=8080
CMD ["python3", "main.py"]
```

Create `.dockerignore` to keep the image small:

```
data/
__pycache__/
*.pyc
.git/
```

The `PORT` environment variable is important — cloud platforms tell your app which port to listen on. Your app must respect it:

```python
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
```

---

## Part 6: Deploying to Google Cloud Run

Cloud Run is Google's service for running containers. It has two properties that make it ideal for small apps:
- **Scales to zero** — when nobody is using the app, it isn't running and you aren't paying for it
- **Permanent HTTPS URL** — you get a stable `*.run.app` address automatically

### One-time setup

1. Create a Google account and go to console.cloud.google.com
2. Create a new **Project** (a billing and permission container for all your resources)
3. Enable billing (required even for free-tier usage — Google needs a card on file)
4. Install the `gcloud` CLI: `curl https://sdk.cloud.google.com | bash`
5. Log in: `gcloud auth login`

### Create supporting infrastructure

```bash
# Artifact Registry — stores your Docker image
gcloud artifacts repositories create your-app \
  --repository-format=docker \
  --location=us-central1

# GCS bucket — stores your data files
gcloud storage buckets create gs://your-app-data \
  --location=us-central1
```

### Build and deploy

```bash
# Build the Docker image on Google's servers (no local Docker needed)
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/YOUR_PROJECT/your-app/app

# Deploy to Cloud Run
gcloud run deploy your-app \
  --image us-central1-docker.pkg.dev/YOUR_PROJECT/your-app/app \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GCS_BUCKET=your-app-data \
  --memory 512Mi
```

After a minute or two, you'll see:
```
Service URL: https://your-app-abc123.us-central1.run.app
```

That URL is permanent.

### Grant permissions

The running container needs permission to read and write your GCS bucket. Find the service account Cloud Run is using and grant it access:

```bash
gcloud storage buckets add-iam-policy-binding gs://your-app-data \
  --member="serviceAccount:YOUR_SERVICE_ACCOUNT@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### Redeploy after changes

Every time you change `main.py`, rebuild and redeploy. A deploy script makes this one command:

```bash
#!/bin/bash
set -e
PROJECT=your-project-id
IMAGE=us-central1-docker.pkg.dev/$PROJECT/your-app/app

gcloud builds submit --tag $IMAGE --project $PROJECT && \
gcloud run deploy your-app \
  --image $IMAGE \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GCS_BUCKET=your-app-data \
  --memory 512Mi \
  --project $PROJECT
```

Save as `deploy.sh`, make it executable (`chmod +x deploy.sh`), and run `./deploy.sh` whenever you want to push an update.

---

## Part 7: Ongoing Development

### The development loop

Once the app is live, the cycle for every new feature is:

1. Edit code locally
2. Run locally (`python3 main.py`) and test the feature
3. `git add` and `git commit`
4. `git push` to GitHub
5. `./deploy.sh` to push to production

### Keep a planned enhancements list

Maintain a simple text file (`planned.md`) of features you want to add. When an idea comes up mid-session and you don't want to break what's working, write it down and come back to it. This keeps scope under control.

### Don't add features you don't need

The biggest time sink in personal projects is building things "just in case." Build what solves today's problem. If a future need arises, add it then — you'll understand it better when it's real.

---

## Summary

| Phase | Key actions |
|---|---|
| Plan | Write user stories, list data you need, sketch screens |
| Setup | Install Python, create virtual environment, install packages |
| Build | Data layer first, one feature at a time, test constantly |
| Version control | Git init, commit often, push to GitHub |
| Prepare for cloud | Abstract storage, write Dockerfile, respect PORT env var |
| Deploy | Cloud Run + GCS, grant permissions, get permanent HTTPS URL |
| Maintain | Edit → test locally → commit → deploy |

The tools change. The pattern doesn't.
