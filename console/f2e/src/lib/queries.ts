import { queryOptions, skipToken } from "@tanstack/react-query";
import { getDetail, getOverview } from "@/api";

export const consoleQueryKey = ["console"] as const;

const polling = {
  refetchInterval: 3000,
  refetchIntervalInBackground: true,
};

export const overviewQueryOptions = queryOptions({
  queryKey: [...consoleQueryKey, "overview"] as const,
  queryFn: ({ signal }) => getOverview(signal),
  ...polling,
});

export function taskenvQueryOptions(target: string | undefined) {
  return queryOptions({
    queryKey: [...consoleQueryKey, "taskenv", target] as const,
    queryFn: target ? ({ signal }) => getDetail(target, signal) : skipToken,
    ...polling,
  });
}
