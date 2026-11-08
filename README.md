# ig-comment-dm

Free "comment TEST and I'll DM you" for your own reels, using Instagram's official API (Meta's Instagram API). It runs entirely on GitHub Actions: every 10 seconds right after you post (burst mode), and every 5 minutes the rest of the time. Anyone who wrote the keyword gets one private reply with your link, and nobody gets it twice.

How it behaves (Meta's rules, from the Private Replies docs, checked Nov 8 2026):
- One private reply per comment, sent within 7 days of the comment.
- If they follow you, the reply lands in their **Inbox**. If not, it goes to their **Requests** folder. That's an honest reason to say "follow so it lands in your inbox".
- Instagram adds a link to the reel inside the reply automatically.
- Replies arrive within about 10 seconds while burst mode is running, and within about 5-15 minutes otherwise (GitHub's 5-minute schedule often starts a few minutes late).

Cost: free, **as long as the repo is public**. Actions minutes are unlimited on public repos. A private repo only gets 2,000 minutes a month: the 5-minute schedule alone would need about 8,600, and one burst uses about 300. Making it public is safe because the token lives in GitHub Secrets, which are never shown publicly and aren't given to forks. The repo itself only holds the script, your reel links, the Drive link (public anyway) and comment IDs.

---

## One-time setup (about an hour)

### 1. Instagram account
1. In the Instagram app: Settings → Account type and tools → **Switch to professional account** → Creator. (Skip this if it's already professional.)
2. Settings → Messages and story replies → Message controls → Connected tools → turn on **Allow access to messages**. Without this the API can't send DMs.

### 2. Meta developer app (Unified login, checked Nov 9 2026)
Meta no longer offers "API setup with Instagram login" to new apps. New apps get **API setup with Unified login**, which is built on Facebook Login for Business and uses host graph.facebook.com. The script defaults to this (`IG_LOGIN=unified`).

1. Log in at business.facebook.com/business/loginpage/?next=https://developers.facebook.com/ with Facebook. Click **Get Started** on developers.facebook.com to register as a developer if you haven't.
2. **My Apps → Create app** → use case **Manage messaging & content on Instagram** → "I don't want to connect a business portfolio yet" → Create app.
3. **Use cases → Customize → API setup with Unified login.** It needs a **business portfolio** (free, no company needed): click + Business portfolio and create one. Skip business verification.
4. **1. Configure your app → Create new configuration.** Keep Expiration **Never** (system-user token). You can untick `ads_management`, `ads_read` and `instagram_content_publish`; keep `instagram_basic`, `instagram_manage_messages` and `instagram_manage_comments`. Select **Use this configuration**. For the redirect URL, any HTTPS page you control works, e.g. this repo's GitHub URL; the script never uses the login flow.
5. **2. Generate access tokens → Add account.** This invites your Instagram account as an **Instagram Tester**. Accept it on instagram.com (web): Settings → Website permissions → Apps and websites → **Tester invites**.
6. **Generate token**, log in, select your Instagram account. Copy the token: it's shown only once. **Don't paste it into chats or any file you commit.**
7. Skip **3. Configure webhooks** and **4. Complete App Review**.

The token never expires (unless you remove the app or move the Instagram account to another portfolio), so there's nothing to renew. The app stays in Development mode with Standard Access. **Confirmed Nov 9 2026:** that's enough to DM commenters who have no role on the app (tested with a non-tester account). If it ever stops working, the next step is App Review for Advanced Access; stop and check before submitting anything.

### 3. Test on your Mac first
```bash
cd ~/Documents/contents/automation/ig-comment-dm
```
```bash
export IG_ACCESS_TOKEN='paste-token-here'
```
```bash
python3 ig_comment_dm.py whoami
```
```bash
python3 ig_comment_dm.py media
```
`whoami` should print your username. `media` lists your recent posts.

Then open `config.json`:
- `reel_url`: the ep 1 reel link (copy link from the app).
- `message`: replace `PASTE_DRIVE_LINK` with the Google Drive link to the self-test PDF (set to "Anyone with the link can view").

Comment `TEST` on the reel from a second account, then do a dry run (sends nothing):
```bash
DRY_RUN=1 python3 ig_comment_dm.py run
```
If it lists your test comment, send it for real once:
```bash
python3 ig_comment_dm.py run
```
Check that the second account got the DM. After this local test, reset `state.json` to `{"media_ids": {}, "replied": {}}` only if you want the test comment to be answered again. Otherwise leave it as it is.

### 4. Put it on GitHub (runs even when your Mac is off)
1. Create a **public** repo on GitHub, for example `ig-comment-dm` (see Cost above for why public). Never commit `.env`; it's already in `.gitignore`.
2. Push this folder to it:
```bash
cd ~/Documents/contents/automation/ig-comment-dm && git init && git add . && git commit -m "comment-to-DM" && git branch -M main
```
```bash
git remote add origin https://github.com/YOUR_USERNAME/ig-comment-dm.git && git push -u origin main
```
3. Repo → Settings → Secrets and variables → Actions → **New repository secret**:
   - `IG_ACCESS_TOKEN`: your Instagram token.
   - (`GH_PAT` is only needed if you switch to the older Instagram Login with `IG_LOGIN=instagram`, whose 60-day tokens the refresh-token job renews. Not needed for Unified login.)
4. Repo → Actions → **comment-dm → Run workflow** to test it. After that it runs every 5 minutes by itself.

---

## 10-second burst (right after you post)

Most keyword comments come in during the first few hours. So right after you post:

1. Add the reel to `config.json` (see "Every new reel") and push.
2. Repo → Actions → **burst-10s → Run workflow**. Keep the defaults (5 hours, every 10 seconds).
3. If the reel is still busy when it finishes, run it again. GitHub caps one job at 6 hours, so one burst lasts at most 5.5.

While a burst runs, the 5-minute job waits its turn (they share a lock), so the two never DM the same person. If Instagram says it's calling too often, the burst pauses (1 minute, then longer) and carries on. If the token expires, it stops and the run shows as failed.

**Fair-use note:** GitHub's terms say Actions is for building and running software projects, not for use as an always-on server. A short burst you start by hand after posting, plus a 5-minute schedule, is ordinary bot use. Running bursts back to back around the clock is the kind of use that could get the repo flagged. Use bursts only for the first hours after a post.

Why not instant webhooks? Meta only sends comment webhooks to apps that are **Live, with Advanced Access and business verification** (Webhooks setup docs, Oct 2026). That needs App Review, which is overkill for one account.

## Public "sent, check your dm" reply
Each campaign can have `comment_replies`: after the DM goes out, the script replies under the comment with one of these texts (rotating, so Instagram doesn't see the same reply hundreds of times). No reply is posted if the DM fails, and a failed reply never causes a second DM. Leave `comment_replies` out of a campaign to turn it off.

Tested live on Nov 9 2026: DM and public reply both worked for a commenter who is not an Instagram Tester, with the app still in Development mode.

## Every new reel
Add a campaign in `config.json` (copy the ep 2 block), set `"active": true`, put in the reel URL, keyword and message, and push. Then start a burst. Set old campaigns to `"active": false` after 7 days, because replies aren't allowed after that anyway (and it saves API calls).

## Files
- `ig_comment_dm.py`: the script (Python standard library only, nothing to install).
- `config.json`: your reels, keywords and messages.
- `state.json`: IDs of comments already answered (no usernames). Committed by the bot after each run.
- `.github/workflows/comment-dm.yml`: runs every 5 minutes.
- `.github/workflows/burst-10s` (`burst.yml`): checks every 10 seconds for up to 5.5 hours; start it by hand after posting.
- `.github/workflows/refresh-token.yml`: manual only; renews a 60-day token if you use `IG_LOGIN=instagram`.
- `tests/`: offline tests (`python3 -m unittest discover -s tests`).

## If something breaks
- **"Invalid OAuth access token"**: the token stopped working (app removed, account moved). Generate a new one (step 2.6) and update the `IG_ACCESS_TOKEN` secret.
- **DMs not sending, error about messaging**: check that "Allow access to messages" is on (step 1.2).
- **"Reel not found"**: the URL in config.json doesn't match. Run `python3 ig_comment_dm.py media` and compare.
- **The Actions tab stops running**: GitHub pauses scheduled jobs after 60 days with no repo activity. Push any change, or run it once by hand.
