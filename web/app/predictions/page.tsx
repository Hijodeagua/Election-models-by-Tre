import Link from 'next/link';
import LastUpdated from '@/app/components/LastUpdated';
import PredictionsBoard from '@/app/components/PredictionsBoard';
import { EmptyState, PageHead } from '@/app/components/ui';
import { getPredictions, getPredictionViews } from '@/app/lib/predictions';

export const metadata = {
  title: "Tre's Senate Picks — Election Oracle",
  description:
    'A map of the 2026 Senate races with hand-made calls and margins, side by side with the polling model.',
};

export default function PredictionsPage() {
  const { as_of } = getPredictions();
  const races = getPredictionViews();

  return (
    <div>
      <PageHead
        kicker="Tre's Picks"
        title="My calls for the 2026 Senate map"
        sub={
          <>
            Not the model — me. Each race on the board gets a winner and a margin, shaded on
            the map from lean to safe, with the{' '}
            <Link href="/senate" className="text-peach underline">
              polling model&rsquo;s
            </Link>{' '}
            median margin alongside so you can see where I&rsquo;m out on a limb.
          </>
        }
      />

      {races.length > 0 ? (
        <PredictionsBoard races={races} asOf={as_of} />
      ) : (
        <EmptyState>No picks yet — add races to web/content/predictions.json.</EmptyState>
      )}

      <LastUpdated />
    </div>
  );
}
