import { useState } from "react";
import * as config from "./config";
import { Header } from "./components/header/Header";
import { Thread } from "./components/thread/Thread";
import { createDemo } from "./demo/demo";
import { useCall } from "./hooks/useCall";
import { useChat } from "./hooks/useChat";
import { useConversation } from "./hooks/useConversation";
import { initialState, isInCall } from "./state/conversation";

export function App() {
  const { state, card, ui, submit } = useConversation(() =>
    config.setupProblem ? initialState({ text: "no server configured", disabled: true }, config.setupProblem) : initialState(),
  );
  const call = useCall(ui, config.backend);
  const chat = useChat(ui, config.backend);
  const [demo] = useState(() => (config.demo ? createDemo(ui, config.demoPace) : null));

  const controls = demo ?? call;
  const sendInput = demo?.sendInput ?? chat.sendInput;
  const onCall = () => (isInCall(state.call.state) ? controls.hangUp() : controls.start());

  return (
    <>
      <Header call={state.call} notice={state.notice} onCall={onCall} onStop={demo ? undefined : chat.optOut} />
      <Thread
        serverLabel={config.serverLabel}
        sessionId={config.sessionId}
        items={state.items}
        card={card}
        onAnswer={(open, answer) => submit(open.spec, answer, sendInput)}
      />
    </>
  );
}
