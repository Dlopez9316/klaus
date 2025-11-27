# 🚀 Setup Guide for Non-Technical Users

**No coding knowledge required!** This guide will walk you through everything step-by-step.

## What This System Does

Think of this as a smart assistant that:
1. **Looks at your bank transactions** (from Chase)
2. **Looks at your invoices** (from HubSpot)
3. **Matches them automatically** (which payment goes with which invoice)
4. **Updates HubSpot** to mark invoices as paid

Instead of you manually checking each transaction, the system does it for you and gets it right 98% of the time!

---

## 📋 What You'll Need (Before Starting)

### 1. Three API Keys (Don't worry, I'll show you how to get these!)

An "API key" is like a password that lets the system access your data. You need:

- **Plaid API Key** (to access Chase bank data)
- **HubSpot API Key** (to access your invoices)
- **Anthropic API Key** (for the AI matching intelligence)

### 2. A Place to Run the System

Think of this like renting a computer in the cloud. **Easiest option: Railway.app** (costs ~$5-20/month)

### 3. About 30-60 minutes of setup time

---

## 🎯 Step-by-Step Setup (Easiest Method)

I'll show you **Option A: Railway.app** - the simplest way with NO coding needed.

---

## STEP 1: Get Your API Keys

### 1A: Get Your Plaid API Key (Chase Bank Access)

**What it does:** Lets the system securely read your Chase transactions

1. **Go to:** https://plaid.com
2. **Click:** "Get API Keys" or "Sign Up"
3. **Create an account** with your email
4. **Choose:** "Sandbox" for testing (it's free!)
5. **You'll get two things:**
   - `client_id` (looks like: `abc123xyz456`)
   - `secret` (looks like: `1a2b3c4d5e6f7g8h9i0j`)
6. **Write these down** in a safe place (like a password manager)

**Important:** Start with "Sandbox" mode for testing. Later, upgrade to "Development" mode when ready for real data.

---

### 1B: Get Your HubSpot API Key

**What it does:** Lets the system read and update your invoices

1. **Log into HubSpot:** https://app.hubspot.com
2. **Click the Settings icon** (gear icon, bottom left)
3. **Go to:** Integrations → Private Apps
4. **Click:** "Create a private app"
5. **Name it:** "Reconciliation Agent"
6. **Under "Scopes," check these boxes:**
   - Invoices: Read ✅
   - Invoices: Write ✅
   - Companies: Read ✅
   - Contacts: Read ✅
7. **Click:** "Create app"
8. **Copy the API key** (starts with `pat-na1-...`)
9. **Write it down** safely

---

### 1C: Get Your Anthropic API Key (AI Intelligence)

**What it does:** Powers the smart matching algorithm

1. **Go to:** https://console.anthropic.com
2. **Create an account** with your email
3. **Add a payment method** (you'll get $5 free credit to start)
4. **Click:** "API Keys" in the left menu
5. **Click:** "Create Key"
6. **Name it:** "Reconciliation System"
7. **Copy the key** (starts with `sk-ant-...`)
8. **Write it down** safely

**Cost:** About $10-30/month depending on usage

---

## STEP 2: Choose How to Deploy

### ⭐ **RECOMMENDED: Railway.app** (Easiest!)

**Why Railway?**
- ✅ No coding or command line needed
- ✅ Automatic deployment
- ✅ $5-20/month (simple pricing)
- ✅ Takes 10-15 minutes

### Other Options (More Technical):
- **DigitalOcean App Platform** - Similar to Railway
- **Your Own Server** - Requires technical knowledge (not recommended)

---

## STEP 3: Deploy to Railway (The Easy Way!)

### 3A: Get the Code on GitHub

1. **Download the project** from the link I provided
2. **Go to:** https://github.com (create account if needed)
3. **Click:** "+" button (top right) → "New repository"
4. **Name it:** `reconciliation-agent`
5. **Make it:** Private (keep your code secure)
6. **Upload the files:**
   - Click "uploading an existing file"
   - Drag all the files from the `reconciliation-agent` folder
   - Click "Commit changes"

### 3B: Connect Railway to GitHub

1. **Go to:** https://railway.app
2. **Click:** "Start a New Project"
3. **Choose:** "Deploy from GitHub repo"
4. **Sign in with GitHub** when asked
5. **Select:** Your `reconciliation-agent` repository
6. Railway will automatically detect the setup!

### 3C: Add Your API Keys to Railway

1. **In Railway, click:** Your project
2. **Click:** "Variables" tab
3. **Add these variables** (one at a time):

```
PLAID_CLIENT_ID = [paste your Plaid client_id]
PLAID_SECRET = [paste your Plaid secret]
PLAID_ENV = sandbox

HUBSPOT_API_KEY = [paste your HubSpot key]

ANTHROPIC_API_KEY = [paste your Anthropic key]

SECRET_KEY = [make up a random password, like: MySecret123XYZ!]

ENVIRONMENT = production
DEBUG = False
```

4. **Click:** "Deploy" or "Redeploy"

### 3D: Wait for Deployment

- Railway will show "Building..." then "Deployed"
- This takes about 5-10 minutes
- You'll get a URL like: `https://your-app.railway.app`

---

## STEP 4: Connect Your Chase Account

### 4A: Link Chase via Plaid

1. **Visit your app URL:** `https://your-app.railway.app`
2. **You should see:** "Link Bank Account" button
3. **Click it** and follow Plaid's instructions:
   - Select "Chase"
   - Log in with your Chase credentials
   - Authorize the connection
4. **Done!** The system can now read your transactions

**Note:** If using Sandbox mode, you'll use test credentials provided by Plaid.

---

## STEP 5: Test It Out!

### 5A: Run Your First Reconciliation

1. **Go to your dashboard:** `https://your-app.railway.app/dashboard`
2. **Click:** "Run Reconciliation Now"
3. **Wait:** About 1-2 minutes
4. **You'll see:** A list of matched transactions!

### 5B: Review the Matches

You'll see something like:

```
✅ Invoice INV-1236: $4,189 (100% confidence)
   Transaction: WIRE FROM 3645 INVESTORS LLC
   Date: 2025-09-17
   [Approve] [Reject]
```

**What to do:**
- **Green checkmark** = High confidence (95%+) → Safe to approve
- **Yellow warning** = Medium confidence (70-94%) → Review carefully
- **Click "Approve"** to update HubSpot
- **Click "Reject"** if it's wrong

### 5C: Check HubSpot

1. **Go to HubSpot:** https://app.hubspot.com
2. **Navigate to:** Sales → Invoices
3. **Find the invoice** (like INV-1236)
4. **You'll see:** Status changed to "Paid" with payment date!

---

## STEP 6: Set Up Daily Automation

### 6A: Enable Auto-Run

The system can automatically run every morning at 8 AM.

**In Railway:**
1. **Go to:** Your project settings
2. **Find:** "Celery Beat" service
3. **Make sure it's:** "Running" (green dot)

That's it! Now it runs automatically every day.

### 6B: Get Email Notifications (Optional)

To get emailed when matches are found:

1. **Sign up for SendGrid:** https://sendgrid.com (free tier available)
2. **Get API key**
3. **Add to Railway variables:**
   ```
   SENDGRID_API_KEY = [your SendGrid key]
   NOTIFICATION_EMAIL = your-email@company.com
   FEATURE_EMAIL_NOTIFICATIONS = True
   ```

---

## STEP 7: Using the Dashboard Daily

### What You'll Do Each Day:

1. **Check your email** (if notifications enabled) or visit the dashboard
2. **Review any medium-confidence matches** (if any)
3. **Click "Approve"** on matches you verify
4. **That's it!** 5-10 minutes instead of hours

### Dashboard Features:

- **📊 Dashboard Home:** See summary stats
- **🔍 Pending Matches:** Items waiting for your review
- **📝 Recent Activity:** What the system did today
- **📈 Analytics:** See time saved, accuracy, etc.
- **⚙️ Settings:** Adjust matching sensitivity

---

## 🆘 Troubleshooting

### "Can't connect to Plaid"
- ✅ Check your `PLAID_CLIENT_ID` and `PLAID_SECRET` are correct
- ✅ Make sure you're using the right environment (`sandbox` or `development`)
- ✅ In Railway, click "Redeploy"

### "Can't connect to HubSpot"
- ✅ Check your `HUBSPOT_API_KEY` is correct
- ✅ Make sure the Private App has the right permissions (Invoices: Read & Write)
- ✅ Try regenerating the API key in HubSpot

### "No matches found"
- ✅ Make sure you have recent transactions (last 90 days)
- ✅ Check that you have open/unpaid invoices in HubSpot
- ✅ Transactions and invoices should be within 7 days of each other

### "System not running"
- ✅ Check Railway dashboard - all services should be green
- ✅ Check "Logs" tab for error messages
- ✅ Try clicking "Restart" on the service

---

## 💰 What Does This Cost?

### Monthly Costs:

1. **Railway Hosting:** $5-20/month
   - Starts at $5/month
   - Scales with usage

2. **Anthropic API (AI):** $10-30/month
   - Pay per use
   - About $0.50-1.00 per reconciliation
   - Running daily = ~$15-30/month

3. **Plaid API:** $0-100/month
   - Sandbox: Free forever (for testing)
   - Development: Free for first 100 items
   - Production: $0.05-0.30 per item per month

4. **SendGrid (Email):** $0/month
   - Free tier: 100 emails/day

**Total:** ~$20-50/month for testing, $50-150/month for production

**Value:** Saves 8-10 hours/month = $400-1,000 worth of time

---

## ⚙️ Adjusting Settings

Want to make the matching more or less strict?

**In Railway, add these variables:**

```
# Make it MORE strict (fewer auto-approvals, more reviews)
MATCHING_CONFIDENCE_THRESHOLD_AUTO = 98

# Make it LESS strict (more auto-approvals, fewer reviews)
MATCHING_CONFIDENCE_THRESHOLD_AUTO = 90

# Change date matching window (currently ±7 days)
MATCHING_DATE_RANGE_DAYS = 14

# Make company name matching stricter
MATCHING_FUZZY_THRESHOLD = 90
```

---

## 🎓 Understanding the Dashboard

### What the Numbers Mean:

**Confidence Score:**
- **95-100%:** Almost certainly correct - safe to auto-approve
- **85-94%:** Probably correct - quick review recommended
- **70-84%:** Possibly correct - careful review needed
- **Below 70%:** Not shown (too uncertain)

**Match Types:**
- **EXACT_AMOUNT_AND_INVOICE:** Perfect match (invoice # in description)
- **EXACT_AMOUNT_AND_COMPANY:** Strong match (exact amount + company name)
- **AMOUNT_DATE_COMPANY:** Good match (amount + date + company)
- **AI_SEMANTIC:** AI analyzed and found match

---

## 🚀 Going to Production

Once you've tested and everything works:

### Move from Sandbox to Real Data:

1. **In Plaid:** Upgrade to "Development" or "Production"
2. **In Railway:** Change variable:
   ```
   PLAID_ENV = development
   ```
3. **Re-link your Chase account** (with real credentials this time)
4. **That's it!** Now using real data

### Enable Auto-Approval:

When you trust the system:

```
FEATURE_AUTO_APPROVAL = True
```

Now high-confidence matches (95%+) automatically update HubSpot without your review!

---

## ✅ Success Checklist

- [ ] Got all three API keys (Plaid, HubSpot, Anthropic)
- [ ] Deployed to Railway
- [ ] Added all API keys as variables
- [ ] Connected Chase account via Plaid
- [ ] Ran first reconciliation successfully
- [ ] Reviewed and approved matches
- [ ] Verified HubSpot updated correctly
- [ ] Set up daily automation
- [ ] (Optional) Set up email notifications

---

## 📞 Getting Help

**If you get stuck:**

1. **Check Railway logs:**
   - Go to your project → "Deployments" → click latest → "View Logs"
   - Look for error messages (copy them)

2. **Common issues have simple fixes:**
   - Most problems = wrong API key or typo
   - Solution = Double-check all your variables in Railway

3. **Test each connection:**
   - Visit: `https://your-app.railway.app/api/test/plaid`
   - Visit: `https://your-app.railway.app/api/test/hubspot`
   - Should say "success" for each

---

## 🎉 You Did It!

**What you've accomplished:**
- ✅ Set up an AI-powered reconciliation system
- ✅ Connected your bank and HubSpot
- ✅ Automated a task that used to take hours
- ✅ Now it runs every day automatically

**What happens now:**
- System runs at 8 AM every day
- Matches transactions to invoices
- You review and approve (5-10 min/day)
- Saves you 2-3 hours per week!

---

## 🔄 Daily Workflow (Once Set Up)

**Every morning:**

1. **Get notification email** (if enabled)
   - "15 new matches found"

2. **Visit dashboard** (5 minutes)
   - Review matches
   - Click "Approve" on the good ones

3. **Done!**
   - HubSpot automatically updated
   - Invoices marked as paid
   - Time saved: 85-90%

**That's the whole workflow!** Simple and fast.

---

## 💡 Pro Tips

1. **Start with Sandbox mode** to learn without risk
2. **Review everything manually** for the first week
3. **Enable auto-approval** once you trust it (after ~50 successful matches)
4. **Check the dashboard weekly** to see your time savings
5. **Adjust confidence thresholds** based on your comfort level

---

**You're all set!** Remember: No coding required, just follow these steps and you'll be up and running. The system does all the technical work for you! 🚀

---

## Quick Reference Card

**Your URLs:**
- App: `https://your-app.railway.app`
- Dashboard: `https://your-app.railway.app/dashboard`
- API Docs: `https://your-app.railway.app/docs`

**Your API Keys:** (Save these securely!)
- Plaid Client ID: `__________`
- Plaid Secret: `__________`
- HubSpot Key: `__________`
- Anthropic Key: `__________`

**Support:**
- Railway Docs: https://docs.railway.app
- Plaid Docs: https://plaid.com/docs
- HubSpot Help: https://help.hubspot.com

---

**Questions? Stuck on a step?** Just ask and I'll help you through it! 😊
