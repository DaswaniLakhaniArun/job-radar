# job-radar

A weekly radar for **cloud and DevOps internships and junior roles**. Every Monday a GitHub Actions workflow searches several job boards, scores each offer with transparent rules and emails me a short list of the new ones. I review and apply myself: nothing is submitted automatically.

## How it works

```
LinkedIn + Indeed (JobSpy) ─┐
Remotive API ───────────────┼─▶ filter & score ─▶ drop offers already sent ─▶ HTML email (Gmail)
Adzuna API ─────────────────┘        (rules)          (state branch)
```

- **Sources:** LinkedIn and Indeed public listings through [JobSpy](https://github.com/speedyapply/JobSpy), the [Remotive](https://remotive.com) remote jobs API and the [Adzuna](https://developer.adzuna.com) API (optional, free key).
- **Scoring:** rule-based and explainable. Role keywords in the title (DevOps, cloud, SRE, platform…), level (internship > junior), matching skills, and penalties for senior titles, years of experience or languages I don't speak. Full-stack and frontend roles are filtered out.
- **Skill gaps:** each offer lists the technologies it asks for that aren't on my CV yet.
- **No repeats:** offers already emailed are stored as hashes on the `state` branch.
- **Cost:** zero. Public repository, standard GitHub-hosted runners, free APIs.

Everything is configured in [`config.yaml`](config.yaml): search terms, locations, keywords and thresholds.

## Setup

1. Add these repository secrets (*Settings → Secrets and variables → Actions*):

   | Secret | Required | Value |
   | --- | --- | --- |
   | `GMAIL_USER` | yes | Gmail address that sends the email |
   | `GMAIL_APP_PASSWORD` | yes | A Gmail [App Password](https://myaccount.google.com/apppasswords) (needs 2-Step Verification) |
   | `MAIL_TO` | no | Recipient, if different from `GMAIL_USER` |
   | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | no | Free keys from developer.adzuna.com; Adzuna is skipped without them |

2. Run *Actions → Weekly job search → Run workflow* once with **dry run** enabled and download the `report` artifact to check the results.
3. Run it again without dry run to receive the first email. After that it runs every Monday.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q
python -m job_radar --dry-run   # writes report.html
```

## Notes

- Job boards change and sometimes block automated requests; a failing source is reported at the bottom of the email and the rest keep working.
- GitHub pauses scheduled workflows in public repositories after 60 days without commits to the default branch. If that happens, re-enable it from the Actions tab.

## Roadmap

- Tailored CV and cover letter for the top offers, generated from a JSON Resume file.
- Local LLM scoring with Ollama.
- Containerise and deploy on AWS with Terraform (as part of my MSc in Cloud & DevOps).

## License

MIT
