import { isInCall, type CallStatus } from "../../state/conversation";
import { AvatarIcon, PhoneIcon } from "../icons";
import { CallTimer } from "./CallTimer";
import { MicMeter } from "./MicMeter";

interface Props {
  call: CallStatus;
  notice: string | null;
  onCall: () => void;
  onStop?: () => void;
}

export function Header({ call, notice, onCall, onStop }: Props) {
  const inCall = isInCall(call.state);
  return (
    <>
      <header className="topbar">
        <div className="avatar" aria-hidden="true"><AvatarIcon /></div>
        <div className="titles">
          <h1>Asha · Hunar hiring</h1>
          <span className="status" data-state={call.state}>
            <span className="status-text" role="status" title={call.text}>{call.text}</span>
            {call.connectedAt !== null && <CallTimer since={call.connectedAt} />}
          </span>
        </div>
        {onStop && (
          <button
            className="stop-btn"
            type="button"
            title="Stop my application"
            onClick={() => {
              if (confirm("Stop your application? You can come back later.")) onStop();
            }}
          >
            Stop
          </button>
        )}
        <button
          className={`call-btn${inCall ? " hangup" : ""}`}
          type="button"
          aria-label={inCall ? "Hang up" : "Start call"}
          title="Use headphones; browser echo cancellation is best-effort."
          disabled={call.disabled}
          onClick={onCall}
        >
          <PhoneIcon />
        </button>
        <MicMeter />
      </header>
      {notice && <p className="notice" role="status">{notice}</p>}
    </>
  );
}
