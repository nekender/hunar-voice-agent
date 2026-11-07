import { todayAt } from "../lib/format";
import { InputKind, type InputRequest } from "../protocol";

export type CardSpec = Omit<InputRequest, "type">;

export interface CallStep {
  label: string;
  ask: string;
  reply: string[];
  values: Record<string, string | boolean | (() => string)>;
  confirm: string;
}

export const CLAIM_REF = "CLM-2026-0042";

export const CALL_STEPS: CallStep[] = [
  {
    label: "account of what happened",
    ask: "Can you tell me what happened?",
    reply: ["I was stopped at", "I was stopped at a signal and a truck", "I was stopped at a signal and a truck hit me from behind."],
    values: { incidentDescription: "Rear-ended by a truck while stopped at a signal" },
    confirm: "I'm sorry to hear that. So you were rear-ended by a truck while stopped.",
  },
  {
    label: "location and time",
    ask: "Where and when was this?",
    reply: ["On MG Road,", "On MG Road, near Trinity metro,", "On MG Road, near Trinity metro, around 9:30 this morning."],
    values: { incidentLocation: "MG Road, near Trinity metro", incidentTime: () => todayAt("09:30:00") },
    confirm: "Got it: MG Road near Trinity metro, today around 9:30.",
  },
  {
    label: "injury details",
    ask: "Was anyone hurt, and can the car still be driven?",
    reply: ["Nobody's hurt.", "Nobody's hurt. The bumper's cracked but it drives fine."],
    values: { injuries: "none", vehicleDrivable: true },
    confirm: "Glad everyone's okay; I've noted the car is drivable.",
  },
];

export const CARDS = {
  policy: {
    id: "reqPolicy", field: "policyNumber", kind: InputKind.TEXT, label: "Policy number",
    help: "Format: POL-123456", placeholder: "POL-123456", required: true, pattern: "^POL-[0-9]{6}$",
  },
  vehicle: {
    id: "reqVehicle", field: "vehicleType", kind: InputKind.SELECT, label: "Which vehicle was involved?", required: true,
    options: [{ value: "car", label: "Car" }, { value: "twoWheeler", label: "Two-wheeler" }, { value: "commercial", label: "Commercial vehicle" }],
  },
  email: { id: "reqEmail", field: "email", kind: InputKind.EMAIL, label: "Email for claim updates (optional)", placeholder: "you@example.com" },
  photos: {
    id: "reqPhotos", field: "damagePhotos", kind: InputKind.FILE, label: "Photos of the damage",
    help: "One or more images", accept: "image/*", multiple: true, required: true,
  },
} satisfies Record<string, CardSpec>;

export const CONFIRM_FIELD = "confirmSubmit";

export const confirmCard = (round: number): CardSpec => ({
  id: `reqConfirm${round}`, field: CONFIRM_FIELD, kind: InputKind.CONFIRM, label: "Submit the claim now?",
});

export const CHAT_ITEMS = [[CARDS.policy.field, "policy number"], [CARDS.vehicle.field, "vehicle"], [CARDS.photos.field, "photos"]];

export const VEHICLES: Record<string, string> = { car: "car", twoWheeler: "two-wheeler", commercial: "commercial vehicle" };

export const SPOKEN_EMAIL = "asha.rao@example.com";

export const RECORD_FIELDS = [
  "incidentDescription", "incidentLocation", "incidentTime", "injuries", "vehicleDrivable",
  "policyNumber", "vehicleType", "damagePhotos", "email",
];
