# Render the matched CPU/GPU benchmark in the GPU protocol figure's style.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
inputs <- read.csv(file.path(args[1], 'per-input.csv'), stringsAsFactors = FALSE)
cells <- read.csv(file.path(args[1], 'synthetic-cells.csv'), stringsAsFactors = FALSE)
fly <- inputs[inputs$family == 'drosophila', ]
fly <- fly[order(fly$case_id), ]
anchors <- inputs[inputs$family == 'human-chimp', ]
anchors <- anchors[order(as.integer(sub('chr', '', anchors$chromosome)), anchors$min_block_bp), ]
stopifnot(nrow(fly) == 6L, nrow(anchors) == 6L, nrow(cells) == 14L)

ink <- '#2C3E50'
gray <- '#7F8C8D'
teal <- '#4b7179'
rust <- '#a3573f'
grid <- '#BFC5C5'
row_shades <- c('#ffffff', '#eeeeee')
top_xlim <- c(0.68, 7.32)
synthetic_limits <- log10(c(0.19, 51))
synthetic_ticks <- c(0.25, 0.5, 1, 2, 4, 8, 16, 32)
real_limits <- log10(c(0.103, 39))
real_ticks <- c(0.125, 0.5, 1, 4, 32)
lengths <- c(2, 4, 8, 16, 32, 64, 128)

open_panel <- function(region, x, y, new = TRUE) {
    par(fig = region, plt = c(0, 1, 0, 1), new = new,
        xaxs = 'i', yaxs = 'i', xpd = NA, las = 1, tcl = -0.29,
        mgp = c(1.2, 0.34, 0), fg = ink, col.axis = ink)
    plot.new()
    plot.window(xlim = x, ylim = y)
}

panel_title <- function(label, outside = 0) {
    coordinates <- par('usr')
    text(coordinates[1] - outside * diff(coordinates[1:2]),
         coordinates[4] + 0.048 * diff(coordinates[3:4]),
         label, adj = c(0, 0), font = 2, cex = 1.045, col = ink)
}

axis_bottom <- function(at, labels) {
    axis(1, at = at, labels = labels, lwd = 0, lwd.ticks = 0.75,
         col.ticks = ink, cex.axis = 0.91)
}

axis_left <- function(at, labels) {
    axis(2, at = at, labels = labels, lwd = 0, lwd.ticks = 0.75,
         col.ticks = ink, cex.axis = 0.91)
}

spines <- function() {
    xy <- par('usr')
    segments(xy[1], xy[3], xy[2], xy[3], col = ink, lwd = 0.8)
    segments(xy[1], xy[3], xy[1], xy[4], col = ink, lwd = 0.8)
}

draw_synthetic_series <- function(family, color, marker) {
    rows <- cells[cells$family == family, ]
    rows <- rows[order(rows$n), ]
    stopifnot(identical(as.numeric(rows$n / 1024), lengths))
    x <- log2(lengths)
    r <- log10(rows$ratio_median)
    lower <- log10(rows$ratio_min)
    upper <- log10(rows$ratio_max)
    segments(x, lower, x, upper, col = color, lwd = 0.76)
    segments(x - 0.06, lower, x + 0.06, lower, col = color, lwd = 0.76)
    segments(x - 0.06, upper, x + 0.06, upper, col = color, lwd = 0.76)
    lines(x, r, col = color, lwd = 1.1)
    points(x, r, pch = marker, cex = 0.72, col = ink, bg = color, lwd = 0.45)
}

synthetic_panel <- function() {
    open_panel(c(0.085, 0.352, 0.248, 0.786), top_xlim, synthetic_limits, new = FALSE)
    abline(h = log10(synthetic_ticks), col = grid, lty = 3, lwd = 0.72, xpd = FALSE)
    abline(h = 0, col = gray, lty = 2, lwd = 0.95, xpd = FALSE)
    draw_synthetic_series('uniform', teal, 23)
    draw_synthetic_series('semi', rust, 24)
    axis_bottom(log2(lengths), lengths)
    axis_left(log10(synthetic_ticks), as.character(synthetic_ticks))
    spines()
    panel_title('(a) Synthetic permutations')
}

case_panel <- function(rows, labels, region, title) {
    open_panel(region, real_limits, c(6.5, 0.5))
    for (i in seq_len(nrow(rows))) {
        rect(real_limits[1], i - 0.5, real_limits[2], i + 0.5,
             border = NA, col = row_shades[(i - 1L) %% 2L + 1L])
    }
    abline(v = log10(real_ticks), col = grid, lty = 3, lwd = 0.72, xpd = FALSE)
    abline(v = 0, col = gray, lty = 2, lwd = 0.95, xpd = FALSE)
    y <- seq_len(nrow(rows))
    lower <- log10(rows$ratio_min)
    upper <- log10(rows$ratio_max)
    segments(lower, y, upper, y, col = teal, lwd = 0.82)
    segments(lower, y - 0.065, lower, y + 0.065, col = teal, lwd = 0.76)
    segments(upper, y - 0.065, upper, y + 0.065, col = teal, lwd = 0.76)
    points(log10(rows$ratio_paired_wall_ms), y, pch = 23, cex = 0.78,
           col = ink, bg = teal, lwd = 0.45)
    axis_bottom(log10(real_ticks), FALSE)
    text(log10(real_ticks), 6.5 + 0.05 * 6, as.character(real_ticks),
         adj = c(0.5, 1), cex = 0.91, col = ink)
    axis_left(y, labels)
    spines()
    panel_title(title, outside = 0.10)
}

pdf(args[2], width = 7.15, height = 2.62, pointsize = 9,
    family = 'Helvetica', useDingbats = FALSE)
synthetic_panel()
fly_labels <- sub('real-v1-dmel-(.*)-([^-]+)$', '\\1 \u00b7 \\2', fly$case_id)
anchor_labels <- paste(anchors$chromosome, anchors$min_block_bp, sep = ' \u00b7 ')
case_panel(fly, fly_labels, c(0.466, 0.655, 0.248, 0.786), '(b) Drosophila gene orders')
case_panel(anchors, anchor_labels, c(0.791, 0.988, 0.248, 0.786), '(c) Human\u2013chimp blocks')

open_panel(c(0, 1, 0, 1), c(0, 1), c(0, 1))
text(0.2185, 0.072, 'Permutation length (\u00d71,024 markers)', col = ink)
text(0.025, 0.516, 'End-to-end speedup vs. CPU', srt = 90, col = ink)
text(0.727, 0.072, 'End-to-end speedup vs. CPU', col = ink)
segments(0.17, 0.95, 0.23, 0.95, col = gray, lty = 2, lwd = 0.95)
text(0.24, 0.95, 'CPU reference', adj = c(0, 0.5), col = ink, cex = 0.94)
segments(0.43, 0.95, 0.49, 0.95, col = teal, lwd = 1.1)
points(0.46, 0.95, pch = 23, cex = 0.78, col = ink, bg = teal, lwd = 0.45)
text(0.50, 0.95, 'Uniform', adj = c(0, 0.5), col = ink, cex = 0.94)
segments(0.64, 0.95, 0.70, 0.95, col = rust, lwd = 1.1)
points(0.67, 0.95, pch = 24, cex = 0.78, col = ink, bg = rust, lwd = 0.45)
text(0.71, 0.95, 'Semi-random (k = 64)', adj = c(0, 0.5), col = ink, cex = 0.94)
dev.off()
