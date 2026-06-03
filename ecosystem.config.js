// Load .env file into process.env
const fs = require("fs");
const path = require("path");
const envPath = path.join(__dirname, ".env");
if (fs.existsSync(envPath)) {
  fs.readFileSync(envPath, "utf8")
    .split("\n")
    .forEach((line) => {
      const [key, ...vals] = line.split("=");
      if (key && vals.length) process.env[key.trim()] = vals.join("=").trim();
    });
}

module.exports = {
  apps: [
    {
      name: "nomi-tunnel",
      script: "/opt/homebrew/bin/cloudflared",
      args: "tunnel --config /Users/chao/.cloudflared/nomi.yml run nomi",
      interpreter: "none",
      autorestart: true,
      watch: false,
    },
    {
      name: "nomi-backend",
      cwd: "/Users/chao/Documents/Projects/nomi/backend",
      script: ".venv/bin/python",
      args: "-m uvicorn app.main:app --host 0.0.0.0 --port 8100 --workers 4",
      interpreter: "none",
      autorestart: true,
      watch: false,
      env: {
        PATH: "/Users/chao/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        NOMI_LLM_PROVIDER: "claude-cli",
        NOMI_GEMINI_API_KEY: process.env.NOMI_GEMINI_API_KEY || "",
      },
    },
  ],
};
