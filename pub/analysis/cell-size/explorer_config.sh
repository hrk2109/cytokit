# source $CYTOKIT_REPO_DIR/pub/analysis/cell-size/explorer_config.sh; cytokit application run_explorer

#export APP_EXP_NAME="20181024-d38-act-20X-5by5"
export APP_EXP_NAME="20181024-d39-act-20x-5by5"
#export APP_EXP_NAME="20181024-d38-unstim-20X-5by5"
#export APP_EXP_NAME="20181024-jurkat-20X-5by5"
#export APP_EXP_NAME="20181024-jurkat2-20X-5by5"
#export APP_EXP_NAME="20181026-pmel-act-60x-5b5"

export APP_EXP_DATA_DIR=$CYTOKIT_DATA_DIR/cytokit/cell-size/20181024/$APP_EXP_NAME/output/v00
export APP_EXP_CONFIG_PATH=$APP_EXP_DATA_DIR/config
export APP_MONTAGE_GRID_ENABLED="false"
export APP_EXTRACT_NAME=best_z_segm
export APP_MONTAGE_NAME=best_z_segm
export APP_MONTAGE_CHANNEL_NAMES="proc_DAPI,proc_MEMB"
export APP_MONTAGE_CHANNEL_COLORS="gray,red"
export APP_PORT=8050
export APP_CELL_IMAGE_BACKGROUND="true"