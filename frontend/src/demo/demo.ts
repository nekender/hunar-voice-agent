import * as mic from "../audio/mic";
import { sessionId } from "../config";
import { isoWithOffset, joinList } from "../lib/format";
import { randomId } from "../lib/ids";
import { ChatServerMessageType, FieldSource, FieldStatus, InputKind, Outcome, Role, type FinalRecord, type RecordField } from "../protocol";
import { CallState } from "../state/conversation";
import type { CallControls, SendInput, Ui } from "../state/ui";
import {
  CALL_STEPS,
  CARDS,
  CHAT_ITEMS,
  CLAIM_REF,
  CONFIRM_FIELD,
  RECORD_FIELDS,
  SPOKEN_EMAIL,
  VEHICLES,
  confirmCard,
  type CallStep,
  type CardSpec,
} from "./script";

const STOP = new Error("call ended");

interface Collected {
  value: unknown;
  source: FieldSource;
  at: string;
}

export function createDemo(ui: Ui, pace: number): CallControls & { sendInput: SendInput } {
  const have: Record<string, Collected> = {};
  const waiters = new Map<string, (value: unknown) => void>();
  const asked = new Set<string>();
  let inCall = false;
  let callGen = 0;
  let calls = 0;
  let callStartedAt = 0;
  let callSeconds = 0;
  let chatSubmissions = 0;
  let policyRejected = false;
  let confirmRound = 1;
  let submitted = false;

  const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms * pace));
  const has = (field: string) => Object.hasOwn(have, field);
  const remember = (field: string, value: unknown, source: FieldSource) => {
    have[field] = { value, source, at: isoWithOffset(new Date()) };
  };
  const isLive = (gen: number) => inCall && gen === callGen;
  const check = (gen: number) => {
    if (!isLive(gen)) throw STOP;
  };

  async function need(gen: number, field: string): Promise<unknown> {
    if (has(field)) return have[field].value;
    const value = await new Promise<unknown>((resolve) => waiters.set(field, resolve));
    check(gen);
    return value;
  }

  async function ask(gen: number, spec: CardSpec) {
    if (asked.has(spec.id)) return;
    await wait(700);
    check(gen);
    asked.add(spec.id);
    ui.showInputCard({ type: ChatServerMessageType.INPUT_REQUEST, ...spec });
  }

  async function agent(gen: number, text: string) {
    check(gen);
    const id = randomId();
    const words = text.split(" ");
    let said = text;
    try {
      for (let i = 3; i < words.length; i += 3) {
        said = words.slice(0, i).join(" ");
        ui.addTranscript({ role: Role.AGENT, id, text: said, final: false });
        await wait(380);
        check(gen);
      }
      said = text;
    } finally {
      ui.addTranscript({ role: Role.AGENT, id, text: said, final: true });
    }
    await wait(700 + text.length * 8);
    check(gen);
  }

  async function user(gen: number, parts: string[]) {
    check(gen);
    const id = randomId();
    for (const [i, text] of parts.entries()) {
      const last = i === parts.length - 1;
      ui.addTranscript({ role: Role.USER, id, text, final: last });
      if (last) break;
      await wait(450 + (parts[i + 1].length - text.length) * 35);
      if (!isLive(gen)) {
        ui.addTranscript({ role: Role.USER, id, text, final: true });
        throw STOP;
      }
    }
    await wait(900 + parts[parts.length - 1].length * 6);
    check(gen);
  }

  function start() {
    inCall = true;
    const gen = ++callGen;
    ui.setCall(CallState.CONNECTING, "connecting…");
    mic.startMic((_pcm, level) => ui.setLevel(level)).catch(() => {});
    setTimeout(() => {
      if (!isLive(gen)) return;
      calls++;
      callStartedAt = Date.now();
      ui.setCall(CallState.CONNECTED, "on call");
      ui.addNote(calls > 1 ? "Call resumed" : "Call started");
      script(gen).catch((err: unknown) => {
        if (err !== STOP) reportError(err);
      });
    }, 1200 * pace);
  }

  function endCall(note: string) {
    if (!inCall) return;
    inCall = false;
    if (callStartedAt) callSeconds += Math.round((Date.now() - callStartedAt) / 1000);
    callStartedAt = 0;
    mic.stopMic();
    ui.setCall(CallState.ENDED, "call ended");
    ui.addNote(note);
  }

  const hangUp = () => endCall("You hung up");

  const sendInput: SendInput = async (spec, value, files) => {
    chatSubmissions++;
    const answer = spec.kind === InputKind.FILE ? files.map((file) => file.name) : value;
    if (spec.field === CARDS.policy.field && !policyRejected) {
      policyRejected = true;
      setTimeout(() => {
        ui.rejectInputCard(spec.id, "We couldn't find that policy. (Demo: the first attempt is always rejected to show an inputError.)");
      }, 1200 * pace);
      return;
    }
    if (spec.kind === InputKind.CONFIRM) confirmRound++;
    remember(spec.field, answer, FieldSource.CHAT);
    const resolve = waiters.get(spec.field);
    waiters.delete(spec.field);
    resolve?.(answer);
  };

  const stepDone = (step: CallStep) => Object.keys(step.values).every(has);

  function welcomeBack(): string {
    const got: string[] = [];
    const missing: string[] = [];
    if (CALL_STEPS.every(stepDone)) got.push("accident details");
    else for (const step of CALL_STEPS) (stepDone(step) ? got : missing).push(step.label);
    for (const [field, label] of CHAT_ITEMS) (has(field) ? got : missing).push(label);
    const needs = [...missing.map((item) => `your ${item}`), "your confirmation"];
    return `Welcome back. ${got.length ? `I have your ${joinList(got)}; ` : ""}I just need ${joinList(needs)}.`;
  }

  async function script(gen: number) {
    if (submitted) {
      await agent(gen, `Hi again. Your claim ${CLAIM_REF} is already submitted; there's nothing else you need to do. Take care!`);
      await wait(800);
      endCall("Call ended");
      return;
    }
    if (has(CONFIRM_FIELD) && !have[CONFIRM_FIELD].value) delete have[CONFIRM_FIELD];

    let lead = calls > 1 ? `${welcomeBack()} ` : "Hi, this is the claims assistant from Acme Insurance. ";
    const take = () => {
      const text = lead;
      lead = "";
      return text;
    };

    for (const step of CALL_STEPS) {
      if (stepDone(step)) continue;
      await agent(gen, take() + step.ask);
      await user(gen, step.reply);
      for (const [field, value] of Object.entries(step.values)) {
        remember(field, typeof value === "function" ? value() : value, FieldSource.CALL);
      }
      lead = `${step.confirm} `;
    }

    if (!has(CARDS.policy.field)) {
      await agent(gen, take() + (asked.has(CARDS.policy.id)
        ? "Your policy number box is still open in the chat."
        : "A few things are easier to type, so I'll send them to the chat one at a time. First, your policy number."));
      await ask(gen, CARDS.policy);
      const policy = await need(gen, CARDS.policy.field);
      lead = `Thanks, I found policy ${String(policy)}. `;
    }

    if (!has(CARDS.vehicle.field)) {
      await agent(gen, `${take()}Next, which vehicle it was${has(CARDS.email.field) ? "." : ", and an email for updates if you'd like them."}`);
      await Promise.all([ask(gen, CARDS.vehicle), has(CARDS.email.field) ? null : ask(gen, CARDS.email)]);
      const vehicle = String(await need(gen, CARDS.vehicle.field));
      lead = `Thanks, a ${VEHICLES[vehicle] ?? vehicle}. `;
    }

    if (!has(CARDS.email.field)) {
      if (lead) await agent(gen, take().trim());
      await user(gen, ["Oh, and for updates", `Oh, and for updates just use ${SPOKEN_EMAIL}.`]);
      remember(CARDS.email.field, SPOKEN_EMAIL, FieldSource.CALL);
      ui.cancelInputCard(CARDS.email.id, "given on the call");
      lead = "Got it, no need to type the email then. ";
    }

    if (!has(CARDS.photos.field)) {
      await agent(gen, `${take()}Last thing: please upload a few photos of the damage.`);
      await ask(gen, CARDS.photos);
      const photos = await need(gen, CARDS.photos.field);
      const count = Array.isArray(photos) ? photos.length : 0;
      lead = `Got ${count} photo${count === 1 ? "" : "s"}. `;
    }

    if (!has(CONFIRM_FIELD)) {
      await agent(gen, `${take()}Everything looks complete; please confirm in the chat.`);
      await ask(gen, confirmCard(confirmRound));
      await need(gen, CONFIRM_FIELD);
    }
    if (!have[CONFIRM_FIELD].value) {
      await agent(gen, `${take()}No problem. I've saved everything; call back whenever you're ready and we'll pick up from here.`);
      return;
    }

    submitted = true;
    await agent(gen, `${take()}Your claim is submitted. Your reference is ${CLAIM_REF}. Take care!`);
    await wait(1400);
    endCall("Call ended: claim submitted");
    await wait(1800);
    ui.showRecord(finalRecord());
  }

  function finalRecord(): FinalRecord {
    const fileUrl = (name: unknown) => `https://files.example.com/${sessionId}/${String(name)}`;
    const fields = Object.fromEntries(RECORD_FIELDS.map((field): [string, RecordField] => {
      const collected = has(field) ? have[field] : null;
      const value = collected?.value ?? null;
      return [field, {
        value: field === CARDS.photos.field && Array.isArray(value) ? value.map(fileUrl) : value,
        source: collected?.source ?? null,
        collectedAt: collected?.at ?? null,
        status: collected ? FieldStatus.VALID : FieldStatus.MISSING,
      }];
    }));
    return {
      sessionId,
      revision: 1,
      outcome: Outcome.COMPLETED,
      outcomeReason: "all required fields collected and valid; user confirmed submission",
      fields,
      conflicts: [],
      engagement: { calls, callSeconds, chatMessages: chatSubmissions },
      costUsd: 0.038,
      endedAt: isoWithOffset(new Date()),
    };
  }

  return { start, hangUp, sendInput };
}
