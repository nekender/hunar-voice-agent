import { useObjectUrl } from "../../hooks/useObjectUrl";
import { isImage } from "../../lib/files";

export function FileRow({ file }: { file: File }) {
  const src = useObjectUrl(isImage(file) ? file : null);
  return (
    <div className="file">
      {src && <img src={src} alt={file.name} />}
      <span>{file.name}</span>
    </div>
  );
}
