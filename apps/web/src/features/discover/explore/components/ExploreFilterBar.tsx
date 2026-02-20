import StreamingServiceFilterChip from "@/features/discover/for_you/components/StreamingServiceFilterChip";
import YearRangeFilterChip from "./YearRangeFilterChip";
import { DEFAULT_YEAR_RANGE } from "@/utils/yearRange";

interface ExploreFilterBarProps {
  selectedProviders: string[];
  onProviderApply: (providers: string[]) => void;
  selectedYearRange: [number, number] | null;
  onYearApply: (range: [number, number] | null) => void;
}

export function ExploreFilterBar({
  selectedProviders,
  onProviderApply,
  selectedYearRange,
  onYearApply,
}: ExploreFilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 pt-1">
      <StreamingServiceFilterChip
        selected={selectedProviders}
        onApply={onProviderApply}
      />
      <YearRangeFilterChip
        value={selectedYearRange}
        onApply={onYearApply}
        min={DEFAULT_YEAR_RANGE[0]}
        max={DEFAULT_YEAR_RANGE[1]}
      />
    </div>
  );
}