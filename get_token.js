import fs from "fs";
import readline from "readline";
import { google } from "googleapis";

const CREDENTIALS_PATH = "credentials.json";
const TOKEN_PATH = "token.json";

// Baca file credentials
function loadCredentials() {
  try {
    const content = fs.readFileSync(CREDENTIALS_PATH);
    return JSON.parse(content).installed;
  } catch (err) {
    console.error("❌ Gagal baca credentials.json:", err.message);
    process.exit(1);
  }
}

async function getAccessToken(oAuth2Client) {
  const authUrl = oAuth2Client.generateAuthUrl({
    access_type: "offline",
    scope: ["https://www.googleapis.com/auth/drive.file"],
  });

  console.log("🔗 Buka URL ini di browser kamu dan login:");
  console.log(authUrl);

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

  const code = await new Promise((resolve) => {
    rl.question("📥 Masukkan kode dari Google: ", (input) => {
      rl.close();
      resolve(input);
    });
  });

  try {
    const { tokens } = await oAuth2Client.getToken(code);
    oAuth2Client.setCredentials(tokens);
    fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokens));
    console.log("✅ Token berhasil disimpan ke", TOKEN_PATH);
  } catch (err) {
    console.error("❌ Gagal mengambil token:", err.message);
    process.exit(1);
  }
}

// Main function
async function main() {
  const { client_id, client_secret, redirect_uris } = loadCredentials();
  const oAuth2Client = new google.auth.OAuth2(client_id, client_secret, redirect_uris[0]);

  await getAccessToken(oAuth2Client);
}

main();
