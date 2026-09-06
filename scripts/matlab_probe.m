% 探测 Simscape Electrical(ee_lib)库里跟配电网建模相关的模块,
% 以及确认 Simulink Fault Analyzer 到底是干什么用的、parsim/SimulationInput是否可用。
try
    load_system('ee_lib');
    fprintf('=== ee_lib loaded OK ===\n');
    names = find_system('ee_lib', 'LookUnderMasks', 'all', 'FindAll', 'off');
    keys = {'Fault', 'PI Section Line', 'Three-Phase Source', 'Series RLC Load', ...
            'Three-Phase V-I Measurement', 'Distributed Parameters Line', 'Breaker', 'Voltage Source'};
    for i = 1:numel(keys)
        k = keys{i};
        matches = {};
        for j = 1:numel(names)
            nm = getfullname(names(j));
            if contains(nm, k, 'IgnoreCase', true)
                matches{end+1} = nm; %#ok<AGROW>
            end
        end
        fprintf('--- 关键词 "%s" 匹配 %d 个 ---\n', k, numel(matches));
        for m = 1:min(numel(matches), 8)
            fprintf('   %s\n', matches{m});
        end
    end
catch ME
    fprintf('ee_lib 探测出错: %s\n', ME.message);
end

fprintf('\n=== parsim / SimulationInput 可用性 ===\n');
fprintf('exist(parsim) = %d\n', exist('parsim', 'file'));
fprintf('exist(Simulink.SimulationInput) = %d\n', exist('Simulink.SimulationInput', 'class'));

fprintf('\n=== Simulink Fault Analyzer 产品说明 ===\n');
try
    v = ver;
    for i = 1:numel(v)
        if contains(v(i).Name, 'Fault', 'IgnoreCase', true)
            fprintf('Name: %s\n', v(i).Name);
        end
    end
    % 尝试拿产品描述
    pl = matlab.addons.installedAddons;
    disp(pl(contains(pl.Name, 'Fault', 'IgnoreCase', true), :));
catch ME2
    fprintf('产品信息探测出错: %s\n', ME2.message);
end
