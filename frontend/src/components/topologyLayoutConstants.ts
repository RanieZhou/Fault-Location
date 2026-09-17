// Shared by TopologyNode (actual rendered box) and dagreLayout (position
// math). They must match exactly: dagre places nodes assuming this size, and
// if the rendered DOM box is even a few pixels off, handles that dagre
// thinks are perfectly aligned end up at different pixel positions --
// turning a straight connector into a barely-visible but real diagonal.
export const NODE_WIDTH = 96
export const NODE_HEIGHT = 40
