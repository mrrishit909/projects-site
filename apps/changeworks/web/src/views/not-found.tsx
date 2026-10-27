import { Link } from "../components/link";
import { PlateHead } from "../components/ui";

export function NotFound() {
  return (
    <>
      <PlateHead mark="No such plate" title="Not found" />
      <p>There is no page at this address. <Link to="">Back to the start</Link> or choose a chapter from the list.</p>
    </>
  );
}
