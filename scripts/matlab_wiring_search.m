mdl = 'wiring_search';
if bdIsLoaded(mdl)
    close_system(mdl, 0);
end
new_system(mdl);

src = add_block('ee_lib/Sources/Voltage Source (Three-Phase)', [mdl '/Source']);
gndn = add_block('ee_lib/Connectors & References/Grounded Neutral (Three-Phase)', [mdl '/GndN']);
eref = add_block('ee_lib/Connectors & References/Electrical Reference', [mdl '/Eref']);
isense = add_block('ee_lib/Sensors & Transducers/Current Sensor (Three-Phase)', [mdl '/Isense']);
load = add_block('ee_lib/Passive/RLC Assemblies/Wye-Connected Load', [mdl '/Load']);
line = add_block('ee_lib/Passive/Lines/Transmission Line (Three-Phase)', [mdl '/Line']);
vsensor = add_block('ee_lib/Sensors & Transducers/Line Voltage Sensor (Three-Phase)', [mdl '/Vsense']);

function ph = P(mdl, name)
    ph = get_param([mdl '/' name], 'PortHandles');
end

function try_pair(mdl, label, p1, p2)
    try
        h = add_line(mdl, p1, p2);
        delete_line(h);
        fprintf('OK   %s\n', label);
    catch ME
        fprintf('fail %s : %s\n', label, ME.message(1:min(60,end)));
    end
end

fprintf('=== Source 的两个port 分别试 GndN 和 Eref ===\n');
try_pair(mdl, 'GndN.L -> Source.L', P(mdl,'GndN').LConn(1), P(mdl,'Source').LConn(1));
try_pair(mdl, 'GndN.L -> Source.R', P(mdl,'GndN').LConn(1), P(mdl,'Source').RConn(1));
try_pair(mdl, 'Eref.L -> Source.L', P(mdl,'Eref').LConn(1), P(mdl,'Source').LConn(1));
try_pair(mdl, 'Eref.L -> Source.R', P(mdl,'Eref').LConn(1), P(mdl,'Source').RConn(1));

fprintf('\n=== Isense 的 RConn1/RConn2 分别试接 Load.LConn1 ===\n');
try_pair(mdl, 'Isense.RConn1 -> Load.L', P(mdl,'Isense').RConn(1), P(mdl,'Load').LConn(1));
try_pair(mdl, 'Isense.RConn2 -> Load.L', P(mdl,'Isense').RConn(2), P(mdl,'Load').LConn(1));
try_pair(mdl, 'Isense.LConn1 -> Load.L', P(mdl,'Isense').LConn(1), P(mdl,'Load').LConn(1));

fprintf('\n=== Isense 的 RConn1/RConn2 分别试接 Line.RConn1(接在线路后面) ===\n');
try_pair(mdl, 'Line.R -> Isense.RConn1', P(mdl,'Line').RConn(1), P(mdl,'Isense').RConn(1));
try_pair(mdl, 'Line.R -> Isense.RConn2', P(mdl,'Line').RConn(1), P(mdl,'Isense').RConn(2));
try_pair(mdl, 'Line.R -> Isense.LConn1', P(mdl,'Line').RConn(1), P(mdl,'Isense').LConn(1));

fprintf('\n=== Vsense 的两个port 分别试 ===\n');
try_pair(mdl, 'Vsense.L -> Load.L', P(mdl,'Vsense').LConn(1), P(mdl,'Load').LConn(1));
try_pair(mdl, 'Vsense.R -> Load.L', P(mdl,'Vsense').RConn(1), P(mdl,'Load').LConn(1));
try_pair(mdl, 'Vsense.L -> Eref.L', P(mdl,'Vsense').LConn(1), P(mdl,'Eref').LConn(1));
try_pair(mdl, 'Vsense.R -> Eref.L', P(mdl,'Vsense').RConn(1), P(mdl,'Eref').LConn(1));

close_system(mdl, 0);
