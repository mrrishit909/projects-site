import { Link } from "../components/link";
import { ViewHead } from "../components/ui";

export function NotFound() {
  return (
    <>
      <ViewHead mark="404" title="Not found"><p className="lede">No such route. The twelve routes are listed in the navigation; <Link to="">start at the observatory</Link>.</p></ViewHead>
    </>
  );
}
