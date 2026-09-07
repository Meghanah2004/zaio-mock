import type { ApiError } from "../services/api";
import { CrossIcon, WarningIcon } from "./icons";

interface ErrorCopy {
  title: string;
  message: string;
  icon: typeof CrossIcon;
}

function copyFor(error: ApiError): ErrorCopy {
  switch (error.kind) {
    case "validation":
      return {
        title: "Check your input",
        message: error.message || "The form has one or more invalid fields. Please check your input and try again.",
        icon: WarningIcon,
      };
    case "rate_limited": {
      const wait = error.retryAfterSeconds ? `Please wait ${error.retryAfterSeconds}s before trying again.` : "Please wait a moment before trying again.";
      return { title: "Rate limit reached", message: `Too many requests. ${wait}`, icon: WarningIcon };
    }
    case "not_found":
      return {
        title: "Result not found",
        message: error.message || "No assessment was found for that paper number.",
        icon: WarningIcon,
      };
    case "network":
      return {
        title: "Network error",
        message: "The API could not be reached. Make sure the backend is running.",
        icon: CrossIcon,
      };
    case "server":
    default:
      return {
        title: "Something went wrong",
        message: "We couldn't complete that request right now. Please try again.",
        icon: CrossIcon,
      };
  }
}

export function ErrorBanner({ error }: { error: ApiError }) {
  const { title, message, icon: Icon } = copyFor(error);

  return (
    <div className="error-state fade-in" role="alert">
      <Icon className="error-state__icon" width={18} height={18} />
      <div>
        <p className="error-state__title">{title}</p>
        <p className="error-state__message">{message}</p>
        {error.requestId && <p className="error-state__meta">Reference: {error.requestId}</p>}
      </div>
    </div>
  );
}
