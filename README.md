# Gọn Link

The Cloudflare Worker serves the frontend and handles redirects; D1 stores short links persistently. It does not use a third-party shortening service. Cloudflare keeps it running when your computer is off and provides a public `workers.dev` address without requiring a custom domain.

You can choose a 3–32 character alias or use a random 12-character code. Rename controls are available in the browser that created a link; a private owner token is stored there. Renaming invalidates the old code. The destination is omitted from browser history and local storage, but becomes visible after a recipient follows the redirect.

## Deploy once

Install Node.js, then open PowerShell in this folder and run:

```powershell
npm install
npx wrangler login
npm run db:create
```

Copy the `database_id` printed by Wrangler into `wrangler.jsonc`, replacing the all-zero placeholder. Initialize the database and deploy:

```powershell
npm run db:init
npm run deploy
```

Wrangler prints the public `https://gon-link.<your-account>.workers.dev` address. Share that address and links created through it; the app then runs on Cloudflare and does not need your PC left on. You only need to deploy again when you change the app.

## Run locally

```powershell
python server.py
```

Open `http://localhost:8000`. Local links only work on this computer. The local Python server uses its own SQLite database and is separate from the deployed D1 database.

## Custom domain

To use `https://ghost-012.com/<code>`, register the domain and attach it to the deployed Worker in Cloudflare. Until DNS and the domain are configured, use the `workers.dev` address printed by Wrangler.
