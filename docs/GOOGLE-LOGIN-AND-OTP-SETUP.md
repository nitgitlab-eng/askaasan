# Google sign-in and forgot-password OTP: step-by-step setup

| | Value |
|---|---|
| Google account (owns the project, sends OTP mail) | `iic.nandhainfotech@gmail.com` |
| Production site | `https://askaasan.com` (also `https://www.askaasan.com`) |
| Staging site | `https://staging.askaasan.com` |
| Local dev (Vite, `pnpm dev`) | `http://localhost:5173` |
| Local Docker (`docker compose`) | `http://localhost:8080` |

## How it works

**Google sign-in** (button on `/login` and `/signup`, API `POST /api/users/google/`):
- **New email**: a user is created in the database (email, Google ID, name, language) and signed in.
- **Email already registered**: the user signs in to that same account, and no duplicate is created.
- **Email registered but never verified**: refused, so nobody can take over an address they registered without owning
  it. The owner does a password reset first, which also verifies the email.

**Forgot password** (`/forgot-password`):
1. The user enters their email and gets a **6-digit code** (valid 15 minutes) plus a backup link (valid 1 hour).
2. The user enters the code. After 5 wrong tries the code stops working and they have to ask for a new one.
3. The user picks a new password and is signed in. All their other sessions are signed out.

---

## Part 1: Google Cloud Console

### Step 1: Sign in
1. Open https://console.cloud.google.com/
2. Sign in as **iic.nandhainfotech@gmail.com**.
3. If Google asks, accept the Terms of Service and choose your country.

### Step 2: Create the project
1. Click the **project picker** in the top bar, next to the Google Cloud logo.
2. Click **New project**.
3. Project name: `Aasan`. Organisation: *No organisation*.
4. Click **Create**, wait for the notification, then click **Select project**.
5. Check that the top bar now shows **Aasan**.

### Step 3: Verify your domain (needed before you publish)
1. Open https://search.google.com/search-console as the same Google account.
2. Click **Add property**, choose **Domain**, enter `askaasan.com`, and click **Continue**.
3. Copy the `google-site-verification=...` TXT record.
4. In your DNS provider for askaasan.com, add a **TXT** record with host `@` and that value.
5. Back in Search Console, click **Verify**. DNS can take a few minutes to update.

### Step 4: OAuth consent screen (Branding)
1. Open the menu **☰** and go to **APIs & Services → OAuth consent screen**. In the new console this page is
   **Google Auth Platform**.
2. Click **Get started**.
3. **App information**:
   - App name: `Aasan`
   - User support email: `iic.nandhainfotech@gmail.com`

   Click **Next**.
4. **Audience**: choose **External** and click **Next**.
5. **Contact information**: `iic.nandhainfotech@gmail.com`, then click **Next**.
6. Tick **I agree** to the user data policy, then click **Continue** and **Create**.
7. Open **Branding** in the left menu and fill in:
   - Application home page: `https://askaasan.com`
   - Application privacy policy link: `https://askaasan.com/privacy`
   - Application terms of service link: `https://askaasan.com/terms`
   - **Authorised domains**: click **+ Add domain** and enter `askaasan.com`. This also covers www and staging.
     Localhost doesn't need to be added here.
   - App logo: leave this empty for now. Uploading a logo means Google has to review the app.

   Click **Save**.

### Step 5: Scopes (Data access)
1. In the left menu, open **Data access** and click **Add or remove scopes**.
2. Tick these three:
   - `openid`
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`
3. Click **Update**, then **Save**. All three are non-sensitive, so Google doesn't need to review them.

### Step 6: Test users (while the app is in Testing)
1. In the left menu, open **Audience**.
2. Under **Test users**, click **+ Add users** and add `iic.nandhainfotech@gmail.com` and each tester's Gmail address.
3. Click **Save**. While the app is in Testing, only these accounts can use Google sign-in.

### Step 7: Create the OAuth client ID
1. In the left menu, open **Clients**, then click **+ Create client**. In the old console this is
   **Credentials → + Create credentials → OAuth client ID**.
2. Application type: **Web application**.
3. Name: `Aasan Web`.
4. Under **Authorised JavaScript origins**, click **+ Add URI** once for each of these. Type them exactly as shown:
   no path, no trailing `/`. If you run local Docker on a different port (`WEB_PORT` in `infra/.env`), add
   `http://localhost:<that port>` as well. Google wants plain `http://localhost` too whenever a localhost port is
   listed.
   ```
   http://localhost
   http://localhost:5173
   http://localhost:8080
   https://askaasan.com
   https://www.askaasan.com
   https://staging.askaasan.com
   ```
5. **Authorised redirect URIs**: leave this empty. The Google button uses a popup, not a redirect.
6. Click **Create**.
7. Copy the **Client ID**. It looks like `1234567890-abcdefg.apps.googleusercontent.com`. The client secret isn't
   needed.

> Google can take 5 minutes to a few hours to accept new origins. If you get "origin_mismatch" right after saving,
> wait and try again.

### Step 8: Put the client ID in the app

**Local (Vite dev, `http://localhost:5173`):**
1. Open `api/.env` and set:
   ```
   GOOGLE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
   FRONTEND_URL=http://localhost:5173
   ```
2. Restart the API: `uv run python manage.py runserver 127.0.0.1:8000`
3. Start the web app from `web/` with `pnpm dev`.
4. Open **http://localhost:5173/login**. Use `localhost`, not `127.0.0.1`, because Google doesn't accept 127.0.0.1
   as an origin here.

> **Docker: which file?** The containers read app settings such as `GOOGLE_CLIENT_ID` from **`api/.env`**.
> `infra/.env` only fills in variables used inside `docker-compose.yml`, which doesn't pass `GOOGLE_CLIENT_ID` on.
> A client ID in `infra/.env` is ignored and the Google button never appears.

**Local Docker (`http://localhost:8080`):**
1. Open `api/.env` and set `GOOGLE_CLIENT_ID=...`. `FRONTEND_URL` for Docker is set in `infra/.env`; its default is
   `http://localhost:8080`.
2. Run `docker compose -f infra/docker-compose.yml up -d --build --force-recreate`.
3. Open **http://localhost:8080/login**.

**Production (`https://askaasan.com`):**
1. On the server, open `api/.env` and set:
   ```
   GOOGLE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
   ```
   `infra/.env` should already contain `FRONTEND_URL=https://askaasan.com`, `WEBAUTHN_ORIGIN=https://askaasan.com` and
   `WEBAUTHN_RP_ID=askaasan.com`. `bash infra/init-env.sh askaasan.com` writes these.
2. Rebuild and restart (the OTP feature is new code):
   `docker compose -f infra/docker-compose.yml --profile voice up -d --build --force-recreate`
3. Open **https://askaasan.com/login**. The **Continue with Google** button should now appear.

**Staging:** do the same with `FRONTEND_URL=https://staging.askaasan.com` in the staging env file.

### Step 9: Test Google sign-in
1. Open `/signup` and click **Continue with Google**. Pick a Gmail address that is a test user and has no account
   yet.
2. You should land on onboarding, and the database now has a new user with that email.
3. Sign out. On `/login`, click **Continue with Google** with the same account.
4. You should be signed in to the same user, with no duplicate created.

### Step 10: Publish (when you're ready for everyone)
1. In the left menu, open **Audience**.
2. Click **Publish app**, then **Confirm**. The status changes to **In production**.
3. Anyone with a Google account can now sign in. Because you only ask for email and profile, Google doesn't need to
   review the app.

---

## Part 2: Send the OTP email from iic.nandhainfotech@gmail.com

> **Local dev without SMTP:** the email, including the 6-digit code, is printed in the terminal running the API. You
> can test the whole flow without these steps. With local Docker, every email lands in the Mailpit inbox at
> **http://localhost:8025** instead.

### Step 1: Turn on 2-Step Verification
1. Open https://myaccount.google.com/security as **iic.nandhainfotech@gmail.com**.
2. Turn on **2-Step Verification**. Google only lets you create app passwords once this is on.

### Step 2: Create an App password
1. Open https://myaccount.google.com/apppasswords
2. App name: `Aasan SMTP`. Click **Create**.
3. Copy the 16-character password. Google shows it only once.

### Step 3: Give the password to Aasan (choose one)

**Option A: Admin console (recommended; this setting overrides `.env`)**
1. Sign in to Aasan as an admin and open **Admin → Email**.
2. Fill in:
   - Host `smtp.gmail.com`, port `587`, TLS **on**
   - User `iic.nandhainfotech@gmail.com`
   - Password: the app password
   - From: `Aasan <iic.nandhainfotech@gmail.com>`
3. Save, then send a test mail.

**Option B: `.env` file.** With Docker (local or the server), put these in **`infra/.env`**. Compose sets the
`EMAIL_*` values itself and overrides anything in `api/.env`. Without Docker (`runserver`), use `api/.env`.
```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=iic.nandhainfotech@gmail.com
EMAIL_HOST_PASSWORD=<16-char app password, no spaces>
DEFAULT_FROM_EMAIL=Aasan <iic.nandhainfotech@gmail.com>
```
Restart after saving. With Docker, the worker sends the mail, so recreate every app container:
`docker compose -f infra/docker-compose.yml up -d --force-recreate api worker beat`.

### Step 4: Test forgot password
1. Open the forgot-password page:
   - Local: `http://localhost:5173/forgot-password`
   - Production: `https://askaasan.com/forgot-password`
2. Enter the email of an existing account and click **Send code**.
3. Open that inbox (or the API terminal in local dev) and copy the 6-digit code.
4. Enter the code and click **Verify code**.
5. Enter the new password twice and click **Save & sign in**. You should now be signed in.
6. Sign out and sign in with the new password to confirm it works.

> Gmail allows about 500 emails a day from a personal account. For production volume, move to a transactional
> provider (Zoho ZeptoMail, Amazon SES, Brevo) sending from `no-reply@askaasan.com`, with SPF and DKIM set up in DNS.
