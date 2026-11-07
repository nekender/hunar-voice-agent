export function ErrorLine({ message }: { message: string | null }) {
  return (
    <p className="card-error" role="alert" hidden={!message}>
      {message}
    </p>
  );
}
