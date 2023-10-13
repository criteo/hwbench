unset parametric
set terminal png
set terminal png size 1920,1080
set output sprintf('%s.png', ARG5)
set style data lines
set key outside top box title "Color legend"
set title ARG2
set xlabel "Time [seconds]"
set xrange [ * : ARG4 ] noreverse writeback
set mxtics 2
set grid xtics
set xtics 10
set ylabel ARG3
set yrange [ 0 : 110 ] noreverse writeback
set grid ytics
set ytics 10
set mytics 5
set y2label ARG3
set zrange [ * : * ] noreverse writeback
set cbrange [ * : * ] noreverse writeback
set rrange [ * : * ] noreverse writeback
set colorbox vertical origin screen 0.9, 0.2 size screen 0.05, 0.6 front  noinvert bdefault

