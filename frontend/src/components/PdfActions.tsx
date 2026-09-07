import { memoPdfUrl, paperPdfUrl } from "../services/api";
import { DownloadIcon } from "./icons";

export function PdfActions({ resultId, available }: { resultId: number; available: boolean }) {
  if (!available) {
    return <p className="pdf-actions__unavailable">PDF was not requested for this result.</p>;
  }

  return (
    <div className="pdf-actions">
      <a className="btn btn--secondary" href={paperPdfUrl(resultId)} target="_blank" rel="noopener noreferrer">
        <DownloadIcon width={15} height={15} />
        Download Paper PDF
      </a>
      <a className="btn btn--secondary" href={memoPdfUrl(resultId)} target="_blank" rel="noopener noreferrer">
        <DownloadIcon width={15} height={15} />
        Download Marking Memo PDF
      </a>
    </div>
  );
}
