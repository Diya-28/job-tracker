# Deploy guide: GitHub (daily job collection) + Netlify (your website)

Why two services: GitHub runs the daily scraper for free and publishes jobs.json. Netlify hosts the swipe page.
Netlify's free plan charges 15 credits per production deploy out of 300 a month, so a deploy every day would use it all.
So the page is deployed to Netlify once, and it reads the daily jobs.json from GitHub Pages.

## Part 1: GitHub (10 minutes)
1. Create a free account at github.com, then New repository. Name it jobwatch. Choose Public (free GitHub Pages needs this).
   The repo holds only job listings and config, nothing personal. Your swipes stay in your browser.
2. Upload this folder's contents so the repo root has: fetch_jobs.py, config.json, netlify.toml, docs/, netlify-site/, .github/workflows/daily.yml
   With git:   cd jobwatch && git init && git add -A && git commit -m "init" && git branch -M main
               git remote add origin https://github.com/YOUR-USERNAME/jobwatch.git && git push -u origin main
   Without git: on the repo page choose Add file > Upload files and drag everything in. If the hidden .github folder doesn't upload,
   choose Add file > Create new file, type .github/workflows/daily.yml as the name, and paste the file's contents.
3. Settings > Pages > Build and deployment > Source: Deploy from a branch > Branch: main, folder /docs > Save.
   After a minute your address is https://YOUR-USERNAME.github.io/jobwatch/
4. Settings > Actions > General > Workflow permissions: choose Read and write permissions > Save.
5. Actions tab > daily-jobs > Run workflow. When it turns green, docs/jobs.json exists and your Pages address shows the deck.
   The first run is slower and Atlassian only records what exists; it lists new Atlassian roles from the second day on.
6. Check the bottom of the deck for "Boards the last run couldn't read". Fix those names in config.json (see Part 4).

## Part 2: Netlify, option A: drag and drop (easiest, 3 minutes)
1. Open netlify-site/config.js in any text editor. Replace YOUR-USERNAME and YOUR-REPO, save.
2. Go to app.netlify.com/drop, sign up or sign in, and drag the whole netlify-site folder onto the page.
3. Your site is live at a random-name.netlify.app address. Rename it under Site configuration > Change site name.
4. Open it. You should see today's jobs. If you see "No jobs loaded yet", the address in config.js is wrong or Part 1 step 5 hasn't finished.
   Test by opening the jobs.json address in a browser tab: you should see JSON text.
5. To change the page later, edit the files and drag the folder onto the site's Deploys page. Each upload costs one deploy.

## Part 2: Netlify, option B: linked to GitHub (auto-updates when you change the page)
1. Edit docs/config.js to set JOBS_URL exactly as in option A, commit it.
2. Netlify > Add new site > Import an existing project > GitHub > pick jobwatch.
3. Branch: main. Base directory: empty. Build command: empty. Publish directory: docs. Deploy.
4. The netlify.toml in the repo makes Netlify skip builds when only jobs.json changed. Check your usage page after a few days to confirm
   skipped builds aren't consuming credits.

## Part 3: Daily use and upkeep
- GitHub runs the job around 07:00 IST, sometimes a little late. Open your Netlify address each morning, swipe, then apply from Interested.
- GitHub can pause scheduled workflows in repos with no activity for a long period. If it does, open Actions and press Enable.
- A custom domain is optional: Netlify > Domain management > Add a domain.

## Part 4: Fixing or adding companies (config.json)
- greenhouse / lever / ashby: use the last part of boards.greenhouse.io/NAME, jobs.lever.co/NAME or jobs.ashbyhq.com/NAME.
- workday: [host, tenant, site]. Open the company's careers page; if the address looks like
  https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/..., then host = nvidia.wd5.myworkdayjobs.com,
  tenant = nvidia (the first word), site = NVIDIAExternalCareerSite.
- smartrecruiters: the name in jobs.smartrecruiters.com/NAME.  amazon: list of countries searched.
- Google, Meta, Apple and Microsoft have no public feed. The deck links to their portals and to 24-hour LinkedIn searches instead.

## What does not run on Netlify
The claude.ai Job Applicator (resume tailoring, Gmail replies, synced tracker) needs claude.ai to run and stays there.
The Netlify page has the swipe deck, match scores, filters, Interested list, mark-applied and CSV export.
