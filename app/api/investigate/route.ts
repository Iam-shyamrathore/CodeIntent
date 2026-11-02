// Compatibility route; all live requests share the service boundary and quotas.
import { POST as proxy } from "../service/[...path]/route";
export async function POST(request: Request) {
  return proxy(request, { params: Promise.resolve({ path: ["investigate"] }) });
}
