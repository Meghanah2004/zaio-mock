import { useRoute } from "../hooks/useRoute";
import { BrandMark } from "./icons";

export function Header() {
  const { navigate } = useRoute();

  return (
    <a
      href="/"
      className="brand"
      aria-label="ZAIO home"
      onClick={(event) => {
        event.preventDefault();
        navigate("/");
      }}
    >
      <span className="brand__mark" aria-hidden="true">
        <BrandMark />
      </span>
      <span className="brand__wordmark">ZAIO</span>
      <span className="brand__divider" aria-hidden="true" />
      <span className="brand__text">
        <span className="text-product-name">Mock EISA</span>
        <span className="brand__subtitle">AI-assisted occupational assessment workspace</span>
      </span>
    </a>
  );
}
