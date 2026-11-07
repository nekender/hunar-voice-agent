import { SendIcon } from "../icons";

export function SendButton() {
  return (
    <button type="submit" className="send" aria-label="Send">
      <SendIcon />
    </button>
  );
}
