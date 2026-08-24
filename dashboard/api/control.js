const crypto = require("crypto");

const REPOSITORY =
  process.env.GITHUB_REPOSITORY || "Rikk96/promo-monitor-brandini";
const BRANCH = "main";
const COMMAND_PATH = "dashboard/command.json";

const ALLOWED_BRANDS = {
  fiat: "Fiat",
  abarth: "Abarth",
  lancia: "Lancia",
  alfa: "Alfa Romeo",
  jeep: "Jeep",
  peugeot: "Peugeot",
  citroen: "Citroen",
  opel: "Opel",
  ds: "DS",
  fiat_pro: "Fiat Professional",
  nissan: "Nissan",
  leapmotor: "Leapmotor",
  honda: "Honda",
  mazda: "Mazda",
  hyundai: "Hyundai",
  mg: "MG",
  omodajaecoo: "Omoda / Jaecoo",
  changan: "Changan",
  bmw: "BMW",
  mini: "MINI",
  dr: "DR",
  lepas: "Lepas",
  dongfeng: "Dongfeng"
};

function send(response, status, data) {
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.setHeader("Cache-Control", "no-store, max-age=0");
  response.status(status).json(data);
}

function validSecret(value) {
  const expected = process.env.DASHBOARD_SECRET || "";
  const received = typeof value === "string" ? value : "";

  const expectedBuffer = Buffer.from(expected);
  const receivedBuffer = Buffer.from(received);

  return (
    expectedBuffer.length > 0 &&
    expectedBuffer.length === receivedBuffer.length &&
    crypto.timingSafeEqual(expectedBuffer, receivedBuffer)
  );
}

async function github(method, body) {
  const token = process.env.GITHUB_TOKEN;

  if (!token) {
    throw new Error("GITHUB_TOKEN non configurato");
  }

  const url =
    `https://api.github.com/repos/${REPOSITORY}/contents/${COMMAND_PATH}`;

  const response = await fetch(url, {
    method,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "promo-monitor-vercel"
    },
    body: body ? JSON.stringify(body) : undefined
  });

  const data = await response.json();

  if (!response.ok) {
    const error = new Error(data.message || `GitHub HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }

  return data;
}

async function readCommand() {
  const file = await github("GET");
  const content = Buffer.from(
    file.content.replace(/\n/g, ""),
    "base64"
  ).toString("utf8");

  return {
    command: JSON.parse(content),
    sha: file.sha
  };
}

module.exports = async function handler(request, response) {
  try {
    if (request.method === "GET") {
      const { command } = await readCommand();
      return send(response, 200, command);
    }

    if (request.method !== "POST") {
      return send(response, 405, { error: "Metodo non consentito" });
    }

    if (!validSecret(request.headers["x-dashboard-secret"])) {
      return send(response, 401, { error: "Password non valida" });
    }

    const body =
      typeof request.body === "string"
        ? JSON.parse(request.body)
        : request.body || {};

    const brand = body.brand;

    if (!Object.prototype.hasOwnProperty.call(ALLOWED_BRANDS, brand)) {
      return send(response, 400, { error: "Brand non autorizzato" });
    }

    const { command: current, sha } = await readCommand();

    if (["PENDING", "RUNNING"].includes(current.status)) {
      return send(response, 409, {
        error: "È già presente un'esecuzione manuale in coda o in corso",
        command: current
      });
    }

    const command = {
      id: crypto.randomUUID(),
      status: "PENDING",
      brand,
      brand_label: ALLOWED_BRANDS[brand],
      requested_at: new Date().toISOString(),
      message: `Aggiornamento manuale ${ALLOWED_BRANDS[brand]} in coda`
    };

    await github("PUT", {
      message: `Dashboard: richiede aggiornamento ${ALLOWED_BRANDS[brand]}`,
      content: Buffer.from(
        JSON.stringify(command, null, 2) + "\n"
      ).toString("base64"),
      branch: BRANCH,
      sha
    });

    return send(response, 202, command);

  } catch (error) {
    console.error(error);

    return send(response, 500, {
      error: "Errore interno del controllo dashboard",
      detail: error.message
    });
  }
};
