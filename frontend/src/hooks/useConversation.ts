import { useCallback, useMemo, useReducer } from "react";
import { errorMessage } from "../lib/errors";
import { clockTime } from "../lib/format";
import { nextKey } from "../lib/ids";
import type { InputRequest } from "../protocol";
import { ActionType } from "../state/actions";
import { isInCall, selectOpenCard, type Answer, type ConversationState } from "../state/conversation";
import { setMicLevel } from "../state/micLevel";
import { conversationReducer } from "../state/reducer";
import type { SendInput, Ui } from "../state/ui";

const SEND_FAILED = "Could not send. Please try again.";

export function useConversation(init: () => ConversationState) {
  const [state, dispatch] = useReducer(conversationReducer, undefined, init);

  const setCall = useCallback<Ui["setCall"]>((callState, text) => {
    dispatch({ type: ActionType.SET_CALL, state: callState, text, now: Date.now() });
    if (!isInCall(callState)) setMicLevel(0);
  }, []);
  const setNotice = useCallback<Ui["setNotice"]>((text) => dispatch({ type: ActionType.SET_NOTICE, text }), []);
  const addTranscript = useCallback<Ui["addTranscript"]>(
    (msg) => dispatch({ type: ActionType.ADD_TRANSCRIPT, msg, key: nextKey(), time: clockTime() }),
    [],
  );
  const addMessage = useCallback<Ui["addMessage"]>(
    (msg) => dispatch({ type: ActionType.ADD_MESSAGE, msg, key: nextKey(), time: clockTime() }),
    [],
  );
  const addNote = useCallback<Ui["addNote"]>((text) => dispatch({ type: ActionType.ADD_NOTE, text, key: nextKey() }), []);
  const showInputCard = useCallback<Ui["showInputCard"]>(
    (spec) => dispatch({ type: ActionType.SHOW_CARD, spec, key: nextKey() }),
    [],
  );
  const rejectInputCard = useCallback<Ui["rejectInputCard"]>(
    (id, message) => dispatch({ type: ActionType.REJECT_CARD, id, message, key: nextKey() }),
    [],
  );
  const cancelInputCard = useCallback<Ui["cancelInputCard"]>(
    (id, reason) => dispatch({ type: ActionType.CANCEL_CARD, id, reason, key: nextKey() }),
    [],
  );
  const showRecord = useCallback<Ui["showRecord"]>(
    (record) => dispatch({ type: ActionType.SHOW_RECORD, record, key: nextKey() }),
    [],
  );

  // useCall/useChat/createDemo key their sockets on `ui`, so its identity must stay stable.
  const ui = useMemo<Ui>(
    () => ({
      setCall,
      setLevel: setMicLevel,
      setNotice,
      addTranscript,
      addMessage,
      addNote,
      showInputCard,
      rejectInputCard,
      cancelInputCard,
      showRecord,
    }),
    [setCall, setNotice, addTranscript, addMessage, addNote, showInputCard, rejectInputCard, cancelInputCard, showRecord],
  );

  const submit = useCallback(async (spec: InputRequest, answer: Answer, send: SendInput) => {
    const key = nextKey();
    dispatch({ type: ActionType.SUBMIT_CARD, id: spec.id, answer, key, time: clockTime() });
    try {
      await send(spec, answer.value, answer.files ?? []);
      dispatch({ type: ActionType.ACK_ANSWER, key });
    } catch (err) {
      dispatch({ type: ActionType.REJECT_CARD, id: spec.id, message: errorMessage(err, SEND_FAILED), key: nextKey() });
    }
  }, []);

  const { active, cards } = state;
  const card = useMemo(() => selectOpenCard({ active, cards }), [active, cards]);

  return { state, card, ui, submit };
}
