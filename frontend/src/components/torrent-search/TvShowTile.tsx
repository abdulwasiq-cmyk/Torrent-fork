import React, { useState, useSyncExternalStore } from 'react';
import { api } from '../../api/client.ts';
import type { TvCatalogueItem } from '../../api/client.ts';
import { formatBytes } from '../../utils/formatters.ts';
import { MoviePrepareCard, imdbTitleLink, type MovieCardImdb } from '../MovieCards.tsx';
import { torrentQualityDetails, torrentResultKey } from './grouping.ts';
import { toCardProviders } from './ottProviders.ts';
import { lowQualityPosterUrl } from './posterUrls.ts';
import { TvShowCard, tvCardModel, tvPosterErrorHandler } from './TvShowCard.tsx';
import { createTvTorrentStore, packScopeLabel, tvShowKey } from './tvTorrentStore.ts';
import { copyMagnetAndOpenWebtor } from './webtor.ts';

// One store for the whole app: one open series card at a time, lookups cached for the session.
// The lookup runs only from a card tap (see tvTorrentStore.open), never on page load or paging.
const tvTorrents = createTvTorrentStore(show =>
  api.getTorrentOptions({ tmdbId: show.id, title: show.title, year: show.year }, undefined, 'all', 'tv'));

type TileShow = Pick<TvCatalogueItem, 'id' | 'title' | 'year' | 'releaseDate' | 'posterUrl' | 'overview' | 'rating' | 'streamingProviders' | 'imdbRating' | 'imdbVotes' | 'imdbId' | 'imdbUrl'>;

/**
 * Series card for every TV / web-series grid. Tapping it looks up the cached season packs:
 * with packs it opens the second card (Play = the existing player flow, Webtor = copy the
 * selected magnet and open Webtor); without packs it plays straight away, as before.
 */
export const TvShowTile: React.FC<{
  show: TileShow;
  imdb?: MovieCardImdb;
  /** The existing playback action for this series (NexStream / VidRift, or Yenime for anime). */
  onPlay: () => void;
}> = ({ show, imdb, onPlay }) => {
  const openKey = useSyncExternalStore(tvTorrents.subscribe, tvTorrents.getOpenKey, tvTorrents.getOpenKey);
  const [selectedKey, setSelectedKey] = useState('');
  const [hint, setHint] = useState('');
  const open = () => tvTorrents.open(show, onPlay);
  if (openKey !== tvShowKey(show)) return <TvShowCard show={show} imdb={imdb} onOpen={open} />;

  const releases = tvTorrents.releasesFor(show);
  const { rating, displayYear, providers } = tvCardModel(show, imdb);
  const selected = releases.find(row => torrentResultKey(row) === selectedKey) || releases[0];
  return (
    <MoviePrepareCard
      posterSrc={show.posterUrl ? lowQualityPosterUrl(show.posterUrl) : ''}
      posterAlt={show.title}
      onPosterClick={tvTorrents.close}
      onPosterLoad={() => {}}
      onPosterError={tvPosterErrorHandler(show.title, displayYear)}
      imdb={rating}
      seeders={selected?.seeders}
      indexer={selected?.indexer}
      quality={selected ? torrentQualityDetails(selected).label : undefined}
      title={show.title}
      titleHref={imdbTitleLink(rating, show.title, displayYear)}
      year={displayYear}
      onClose={tvTorrents.close}
      providers={toCardProviders(providers)}
      variants={releases.map(row => ({
        key: torrentResultKey(row),
        label: `${packScopeLabel(row)} · ${torrentQualityDetails(row).label || 'Unknown'} · ${formatBytes(Number(row.size) || 0)} · ▲${Number(row.seeders) || 0}${row.indexer ? ` · ${row.indexer}` : ''}`,
      }))}
      selectedVariantKey={selected ? torrentResultKey(selected) : ''}
      onSelectVariant={key => { setSelectedKey(key); setHint(''); }}
      variantsAriaLabel={`Choose season or quality for ${show.title}`}
      prepared={null}
      directStream={{ label: 'Play', disabled: false, onClick: onPlay }}
      webtor={selected?.magnetUrl ? {
        label: 'Webtor',
        hint,
        onClick: () => {
          const copied = copyMagnetAndOpenWebtor(String(selected.magnetUrl));
          setHint(copied
            ? 'Magnet copied. Paste it on Webtor to stream or download.'
            : 'Webtor opened, but the magnet could not be copied. Select another pack and try again.');
        },
      } : undefined}
    />
  );
};
