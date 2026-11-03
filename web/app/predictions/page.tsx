import Link from 'next/link';
import LastUpdated from '@/app/components/LastUpdated';
import PredictionsBoard from '@/app/components/PredictionsBoard';
import PublicGuesses, { type GuessRace } from '@/app/components/PublicGuesses';
import { EmptyState, PageHead } from '@/app/components/ui';
import { allowedPicksFor, marketCall, modelGuess, positiveSide } from '@/app/lib/guesses-shared';
import { getSenateForecast } from '@/app/lib/data';
import { getPredictions, getPredictionViews } from '@/app/lib/predictions';
import type { PredictionRaceView } from '@/app/lib/predictions-shared';

function toGuessRaces(races: PredictionRaceView[]): GuessRace[] {
  const allowed = allowedPicksFor(races);
  const markets = new Map((getSenateForecast()?.races ?? []).map((f) => [f.state, f.market_dem_prob]));
  return races.map((r) => ({
    abbr: r.abbr,
    state: r.state,
    dem_candidate: r.dem_candidate,
    rep_candidate: r.rep_candidate,
    ind_candidate: r.ind_candidate,
    allowed: allowed[r.abbr],
    hijodeagua: r.pick ? { pick: r.pick, margin: r.margin } : null,
    model: modelGuess(r),
    market: marketCall(markets.get(r.state), positiveSide(r)),
  }));
}

export const metadata = {
  title: "Hijodeagua's Guesses | Election Oracle",
  description:
    'A map of the 2026 Senate races with hand-made calls and margins, side by side with the polling model.',
};

export default function PredictionsPage() {
  const { as_of } = getPredictions();
  const races = getPredictionViews();

  return (
    <div>
      <PageHead
        kicker="Hijodeagua's Guesses"
        title="Hijodeagua's guesses for the 2026 Senate map"
        sub={
          <>
            Not the model — a human guess. Each race on the board gets a winner and a margin, shaded on
            the map from lean to safe, with the{' '}
            <Link href="/senate" className="text-peach underline">
              polling model&rsquo;s
            </Link>{' '}
            median margin alongside so you can see where I&rsquo;m out on a limb.
          </>
        }
      />

      {races.length > 0 ? (
        <>
          <PredictionsBoard races={races} asOf={as_of} />
          <PublicGuesses races={toGuessRaces(races)} />
        </>
      ) : (
        <EmptyState>No picks yet — add races to web/content/predictions.json.</EmptyState>
      )}

      <LastUpdated />
    </div>
  );
}
