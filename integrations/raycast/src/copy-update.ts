import { copyFromEod } from "./run";

export default async function Command() {
  await copyFromEod("--standup", "Update copied", "No work recorded today yet");
}
