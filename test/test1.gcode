; Test G-code for 3D printer

;Ender 3


G92 E0 ; Reset Extruder
G28 ; Home all axes
G1 Z2.0 F3000 ; Move Z Axis up little to prevent scratching of Heat Bed
G1 X0.1 Y20 Z0.3 F5000.0 ; Move to start position
G1 X0.1 Y200.0 Z0.3 F1500.0 E15 ; Draw the first line
G1 X0.4 Y200.0 Z0.3 F5000.0 ; Move to side a little
G1 X0.4 Y20 Z0.3 F1500.0 E30 ; Draw the second line
G92 E0 ; Reset Extruder
G1 Z2.0 F3000 ; Move Z Axis up little to prevent scratching of Heat Bed
G1 X5 Y20 Z0.3 F5000.0 ; Move over to prevent blob squish
;start of print



G21 ; set units to millimeters
G90 ; absolute positioning
M82 ; absolute extrusion mode

G1 X0 Y0 Z0.3 F1500
G1 X50 Y0 E1.5
G1 X50 Y50 E3.0
G1 X0 Y50 E4.5
G1 X0 Y0 E6.0

G1 X10 Y10 E6.5
G1 X40 Y10 E7.2
G1 X40 Y40 E8.0
G1 X10 Y40 E9.0



;end of print
G91 ;Relative positioning
G1 E-2 F2700 ;Retract a bit
G1 E-2 Z0.2 F2400 ;Retract and raise Z
G1 X5 Y5 F3000 ;Wipe out
G1 Z10 ;Raise Z more
G90 ;Absolute positioning

G1 X0 Y{machine_depth} ;Present print
M106 S0 ;Turn-off fan
M104 S0 ;Turn-off hotend
M140 S0 ;Turn-off bed

M84 X Y E ;Disable all steppers but Z

