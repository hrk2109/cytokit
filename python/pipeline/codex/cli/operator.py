import fire
import os
import os.path as osp
import numpy as np
import pandas as pd
from codex import config as codex_config
from codex.ops import cytometry
from codex.ops import analysis
from codex.ops import tile_generator
from codex.ops import tile_crop
from codex import io as codex_io
from codex import cli
import logging

CH_SRC_RAW = 'raw'
CH_SRC_PROC = 'proc'
CH_SRC_CYTO = 'cyto'
CH_SOURCES = [CH_SRC_RAW, CH_SRC_PROC, CH_SRC_CYTO]

PATH_FMT_MAP = {
    CH_SRC_RAW: None,
    CH_SRC_PROC: codex_io.FMT_PROC_IMAGE,
    CH_SRC_CYTO: codex_io.FMT_CYTO_IMAGE
}


def _get_channel_source(channel):
    res = None
    for src in CH_SOURCES:
        if channel.startswith(src + '_'):
            res = src
    return res


def _map_channels(config, channels):
    res = []
    for channel in channels:
        src = _get_channel_source(channel)
        if src is None:
            raise ValueError(
                'Channel with name "{}" is not valid.  Must start with one of the following: {}'
                .format(channel, [c + '_' for c in CH_SOURCES])
            )
        channel = '_'.join(channel.split('_')[1:])
        if src == CH_SRC_RAW or src == CH_SRC_PROC:
            coords = config.get_channel_coordinates(channel)
            res.append([channel, src, coords[0], coords[1]])
        elif src == CH_SRC_CYTO:
            coords = cytometry.get_channel_coordinates(channel)
            res.append([channel, src, coords[0], coords[1]])
        else:
            raise AssertionError('Source "{}" is invalid'.format(src))
    return pd.DataFrame(res, columns=['channel_name', 'source', 'cycle_index', 'channel_index'])


def _get_z_slice_fn(z, data_dir):
    """Get array slice map to be applied to z dimension

    Args:
        z: String or 1-based index selector for z indexes constructed as any of the following:
            - "best": Indicates that z slices should be inferred based on focal quality
            - "all": Indicates that a slice for all z-planes should be used
            - str or int: A single value will be interpreted as a single index
            - tuple: A 2-item or 3-item tuple forming the slice (start, stop[, step]); stop is inclusive
            - list: A list of integers will be used as is
        data_dir: Data directory necessary to infer 'best' z planes
    Returns:
        A function with signature (region_index, tile_x, tile_y) -> slice_for_array where slice_for_array
        will either be a slice instance or a list of z-indexes (Note: all indexes are 0-based)
    """
    if not z:
        raise ValueError('Z slice cannot be defined as empty value (given = {})'.format(z))

    # Look for keyword strings
    if isinstance(z, str) and z == 'best':
        map = analysis.get_best_focus_coord_map(data_dir)
        return lambda ri, tx, ty: [map[(ri, tx, ty)]]
    if isinstance(z, str) and z == 'all':
        return lambda ri, tx, ty: slice(None)

    # Parse argument as 1-based index list and then convert to 0-based
    zi = cli.resolve_index_list_arg(z, zero_based=True)
    return lambda ri, tx, ty: zi


def _get_tile_locations(config, region_indexes, tile_indexes):
    res = []
    for tile_location in config.get_tile_indices():
        if region_indexes is not None and tile_location.region_index not in region_indexes:
            continue
        if tile_indexes is not None and tile_location.tile_index not in tile_indexes:
            continue
        res.append(tile_location)
    return res


class Operator(cli.CLI):

    def extract(self, name, channels, z='best', region_indexes=None, tile_indexes=None):
        """Create a new data extraction include either raw, processed, or cytometric imaging data

        Args:
            name: Name of extraction to be created; This will be used to construct result path like
                EXP_DIR/output/extract/`name`
            channels: List of strings indicating channel names (case-insensitive)
            z: String or 1-based index selector for z indexes constructed as any of the following:
                - "best": Indicates that z slices should be inferred based on focal quality
                - "all": Indicates that a slice for all z-planes should be used
                - str or int: A single value will be interpreted as a single index
                - tuple: A 2-item or 3-item tuple forming the slice (start, stop[, step]); stop is inclusive
                - list: A list of integers will be used as is
            region_indexes: 1-based sequence of region indexes to process; can be specified as:
                - None: Region indexes will be inferred from experiment configuration
                - str or int: A single value will be interpreted as a single index
                - tuple: A 2-item or 3-item tuple forming the slice (start, stop[, step]); stop is inclusive
                - list: A list of integers will be used as is
            tile_indexes: 1-based sequence of tile indexes to process; has same semantics as `region_indexes`
        """
        channel_map = _map_channels(self.config, channels).groupby('source')
        channel_sources = sorted(list(channel_map.groups.keys()))

        z_slice_fn = _get_z_slice_fn(z, self.data_dir)
        region_indexes = cli.resolve_index_list_arg(region_indexes, zero_based=True)
        tile_indexes = cli.resolve_index_list_arg(tile_indexes, zero_based=True)

        logging.info('Creating extraction "{}" ...'.format(name))

        tile_locations = _get_tile_locations(self.config, region_indexes, tile_indexes)

        extract_path = None
        for i, loc in enumerate(tile_locations):
            logging.info('Extracting tile {} of {}'.format(i+1, len(tile_locations)))
            extract_tile = []
            for src in channel_sources:
                generator = tile_generator.CodexTileGenerator(
                    self.config, self.data_dir, loc.region_index, loc.tile_index,
                    mode='raw' if src == CH_SRC_RAW else 'stack',
                    path_fmt_name=PATH_FMT_MAP[src]
                )
                tile = generator.run(None)

                # Crop raw images if necessary
                if src == CH_SRC_RAW:
                    tile = tile_crop.CodexTileCrop(self.config).run(tile)

                for _, r in channel_map.get_group(src).iterrows():
                    z_slice = z_slice_fn(loc.region_index, loc.tile_x, loc.tile_y)
                    # Extract (z, h, w) subtile
                    sub_tile = tile[r['cycle_index'], z_slice, r['channel_index']]
                    logging.debug(
                        'Extraction for cycle %s, channel %s (%s), z slice %s, source "%s" complete (tile shape = %s)',
                        r['cycle_index'], r['channel_index'], r['channel_name'], z_slice, src, sub_tile.shape
                    )
                    assert sub_tile.ndim == 3, \
                        'Expecting sub_tile to have 3 dimensions but got shape {}'.format(sub_tile.shape)
                    extract_tile.append(sub_tile)

            # Stack the subtiles to give array with shape (z, channels, h, w) and then reshape to 5D
            # format like (cycles, z, channels, h, w)
            extract_tile = np.stack(extract_tile, axis=1)[np.newaxis]
            assert extract_tile.ndim == 5, \
                'Expecting extract tile to have 5 dimensions but got shape {}'.format(extract_tile.shape)

            extract_path = codex_io.get_extract_image_path(loc.region_index, loc.tile_x, loc.tile_y, name)
            extract_path = osp.join(self.data_dir, extract_path)
            logging.debug(
                'Saving tile with shape %s (dtype = %s) to "%s"',
                extract_tile.shape, extract_tile.dtype, extract_path
            )
            codex_io.save_tile(extract_path, extract_tile)

        logging.info('Extraction complete (results saved to %s)', osp.dirname(extract_path) if extract_path else None)


if __name__ == '__main__':
    fire.Fire(Operator)