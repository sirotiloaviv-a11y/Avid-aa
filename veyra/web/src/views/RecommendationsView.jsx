import { useVeyra } from '../lib/VeyraContext.jsx';
import { RecommendationsFeed } from '../components/Recommendations.jsx';

export function RecommendationsView() {
  const { data } = useVeyra();
  return <RecommendationsFeed recommendations={data.recommendations} integrations={data.integrations} showFilters />;
}
