# ig-comment-dm

Free "comment TEST and I'll DM you" for your own reels, using Instagram's official API (the same API ManyChat uses). It runs entirely on GitHub Actions: every 10 seconds right after you post (burst mode), and every 5 minutes the rest of the time. Anyone who wrote the keyword gets one private reply with your link, and nobody gets it twice.

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

### 2. Meta developer app
1. Go to developers.facebook.com and log in. Register as a developer if it asks.
2. **My Apps → Create app.** Pick the use case for managing messaging and content on Instagram (the wording changes; it's the Instagram API one). Choose **Business** if it asks for a type.
3. In the app dashboard, open **Instagram → API setup with Instagram login**.
4. Under **Generate access tokens**, add your Instagram account and log in with it. Approve these permissions:
   - `instagram_business_basic`
   - `instagram_business_manage_comments`
   - `instagram_business_manage_messages`
5. Copy the token it gives you. **Don't paste it into chats, Discord, or any file you commit.**

The app can stay in Development mode. That's enough for your own account, which has a role on the app. If Meta asks for App Review or Advanced Access, stop and check before submitting anything.

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
   - `GH_PAT`: a fine-grained GitHub token (github.com/settings/personal-access-tokens) for **this repo only**, with **Secrets: Read and write**. The weekly job uses it to save the renewed Instagram token.
4. Repo → Actions → **comment-dm → Run workflow** to test it. After that it runs every 5 minutes by itself.
5. Run **refresh-token** once by hand to check that the renewal works.

---

## 10-second burst (right after you post)

Most keyword comments come in during the first few hours. So right after you post:

1. Add the reel to `config.json` (see "Every new reel") and push.
2. Repo → Actions → **burst-10s → Run workflow**. Keep the defaults (5 hours, every 10 seconds).
3. If the reel is still busy when it finishes, run it again. GitHub caps one job at 6 hours, so one burst lasts at most 5.5.

While a burst runs, the 5-minute job waits its turn (they share a lock), so the two never DM the same person. If Instagram says it's calling too often, the burst pauses (1 minute, then longer) and carries on. If the token expires, it stops and the run shows as failed.

**Fair-use note:** GitHub's terms say Actions is for building and running software projects, not for use as an always-on server. A short burst you start by hand after posting, plus a 5-minute schedule, is ordinary bot use. Running bursts back to back around the clock is the kind of use that could get the repo flagged. Use bursts only for the first hours after a post.

Why not instant webhooks? Meta only sends comment webhooks to apps that are **Live, with Advanced Access and business verification** (Webhooks setup docs, Oct 2026). That needs App Review, which is overkill for one account.

## Every new reel
Add a campaign in `config.json` (copy the ep 2 block), set `"active": true`, put in the reel URL, keyword and message, and push. Then start a burst. Set old campaigns to `"active": false` after 7 days, because replies aren't allowed after that anyway (and it saves API calls).

## Files
- `ig_comment_dm.py`: the script (Python standard library only, nothing to install).
- `config.json`: your reels, keywords and messages.
- `state.json`: IDs of comments already answered (no usernames). Committed by the bot after each run.
- `.github/workflows/comment-dm.yml`: runs every 5 minutes.
- `.github/workflows/burst-10s` (`burst.yml`): checks every 10 seconds for up to 5.5 hours; start it by hand after posting.
- `.github/workflows/refresh-token.yml`: renews the 60-day Instagram token every Monday.
- `tests/`: offline tests (`python3 -m unittest discover -s tests`).

## If something breaks
- **"Invalid OAuth access token"**: the token expired. Generate a new one (step 2.4) and update the `IG_ACCESS_TOKEN` secret.
- **DMs not sending, error about messaging**: check that "Allow access to messages" is on (step 1.2).
- **"Reel not found"**: the URL in config.json doesn't match. Run `python3 ig_comment_dm.py media` and compare.
- **The Actions tab stops running**: GitHub pauses scheduled jobs after 60 days with no repo activity. Push any change, or run it once by hand.
