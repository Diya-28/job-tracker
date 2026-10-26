# jobwatch: daily fresh jobs + swipe deck (India + abroad)
1. New GitHub repo, upload all files (keep the .github folder and docs/index.html).
2. Settings > Pages > Deploy from branch > main, folder /docs.
3. Actions > daily-jobs > Run workflow once. After that it runs daily at 07:00 IST and updates docs/jobs.json.
4. Your deck: https://<username>.github.io/<repo>/  (swipe right = keep, left = skip; choices stay in your browser).

How the match score works: it finds the skills a job description mentions (about 45 tracked skills), then reports the share
that your resume already shows, with a small bonus for a core AI/ML title and a penalty for 6+/7+ years asked. Green chips are
skills you have, amber chips are gaps. It measures skill-keyword coverage, not overall fit. Short descriptions get a rough 40-50.
The skill list lives at the top of fetch_jobs.py (SKILLS). Set the second number to 1 or 0 as your resume changes.

Run locally: python3 fetch_jobs.py (Python 3.9+, nothing to install). Edit config.json to add companies or regions.
Interested jobs: use "Copy for tracker" and paste into the Add job tab of your Job Applicator.

## v4 additions
Sources now: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Amazon and Atlassian. See DEPLOY.md for GitHub + Netlify steps.
