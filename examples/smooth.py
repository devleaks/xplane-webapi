import csv

data = []
last_val = 0
with open("vs.csv", "r") as fp:
    reader = csv.reader(fp)
    for line in reader:
        d = [float(j) for j in line]
        L = len(d)
        if d[3] != last_val:
            last_val = d[3]
        data.append(d + [1, 1, 1, 1, 0])

# 0=index 1=timestamp, 2=vertical speed, 3=true_theta, 4=value, 5=g, 6=g low pass

print("data", len(data))

_display_g = [1, 1]
G = 9.80665

# compute G (as derivative of vertical speed)
where = 4000
size = 200

TS = 1
VS = 4

print(f"** index                ts        vs         g       g_lp      g       g_lp    lp_min   lp_max")
# Initialize
for i in range(where, where + 2):
    g = 1
    g_lp = 1
    data[i][L+0] = g
    data[i][L+1] = g_lp
    _display_g = (min(_display_g[0], g_lp), max(_display_g[1], g_lp))
    data[i][L+2] = _display_g[0]
    data[i][L+3] = _display_g[1]
    data[i][L+4] = data[i][VS]
    print(f"** {int(data[i][0]):5d} {data[i][TS]:12.6f} {data[i][VS]:12.6f} {' '.join([f'{v:8.2f}' for v in data[i][L-2:L+5]])} {data[i][L-1]-data[i][L+1]:8.2f}")

for i in range(where + 2, where+size):
    vs0 = data[i][VS]
    vs1 = data[i-1][VS]
    vs2 = data[i-2][VS]
    ts = data[i][TS]
    t10 = (data[i-1][TS] - ts)
    t20 = (data[i-2][TS] - ts)
    t21 = (data[i-2][TS] - data[i-1][TS])
    g = 1.0 + (-vs2 * t21 / (t10 * t20) + vs1 / t10 - vs1 / t21 + vs0 * t10 / (t21 * t20)) / G

    # MAX_G = 10
    # g = min(g, MAX_G)
    # g = max(-MAX_G, g)

    data[i][L] = g

    g_lp = 1
    # 0=timestamp, 1=vertical speed, 2=true_theta, 3=value, 4=g, 5=g low pass
    # data.append([ts, vs, tt, val, g, g_lp])
    # compute G low pass filtered
    LP = 5
    if (i+where) > LP:
        total = 0
        smovs = 0
        for k in range(2, LP+1):  # LP+1?
            total = total + data[i-k][L] * (data[i-k + 1][TS] - data[i-k][TS])
            smovs = smovs + data[i-k][VS] * (data[i-k + 1][TS] - data[i-k][TS])
        g_lp = total / (data[i-1][TS] - data[i-LP][TS])
        vs_lp = smovs / (data[i-1][TS] - data[i-LP][TS])
        data[i][L+1] = g_lp
        # data[i][L+4] = vs_lp
    else:
        data[i][L+1] = g

    LP = 10
    if (i+where) > LP:
        smovs = 0
        for k in range(2, LP+1):  # LP+1?
            smovs = smovs + data[i-k][VS] * (data[i-k + 1][TS] - data[i-k][TS])
        vs_lp = smovs / (data[i-1][TS] - data[i-LP][TS])
        data[i][L+4] = vs_lp
    else:
        data[i][L+4] = data[i][VS]

    _display_g = (min(_display_g[0], g_lp), max(_display_g[1], g_lp))
    # data[i][L+2] = _display_g[0]
    # data[i][L+3] = _display_g[1]
    # print(f">> {i:5d} {ts:18.6f} {data[i][1]:12.6f} {g:6.2f} {g_lp:6.2f} {_display_g[0]:6.2f} {_display_g[1]:6.2f}")

    # print(f"** {int(data[i][0]):5d} {data[i][TS]:12.6f} {data[i][VS]:12.6f} {' '.join([f'{v:8.2f}' for v in data[i][L-2:L+5]])} {data[i][L-1]-data[i][L+1]:8.2f}")

    # if dataref_value(DREFS.Y_AGL) < 10 and dataref_value(DREFS.GROUND_SPEED) > 60:
    #     print(f"{data[-1][0].strftime('%S.%f')}, vs={round(vs,2)} g={round(g, 2)} lpg={round(g_lp, 2)}")


VS = L+4

for i in range(where + 2, where+size):
    vs0 = data[i][VS]
    vs1 = data[i-1][VS]
    vs2 = data[i-2][VS]
    ts = data[i][TS]
    t10 = (data[i-1][TS] - ts)
    t20 = (data[i-2][TS] - ts)
    t21 = (data[i-2][TS] - data[i-1][TS])
    g = 1.0 + (-vs2 * t21 / (t10 * t20) + vs1 / t10 - vs1 / t21 + vs0 * t10 / (t21 * t20)) / G

    # MAX_G = 10
    # g = min(g, MAX_G)
    # g = max(-MAX_G, g)

    data[i][L] = g

    g_lp = 1
    # 0=timestamp, 1=vertical speed, 2=true_theta, 3=value, 4=g, 5=g low pass
    # data.append([ts, vs, tt, val, g, g_lp])
    # compute G low pass filtered
    LP = 5
    if (i+where) > LP:
        total = 0
        smovs = 0
        for k in range(2, LP+1):  # LP+1?
            total = total + data[i-k][L] * (data[i-k + 1][TS] - data[i-k][TS])
        g_lp = total / (data[i-1][TS] - data[i-LP][TS])
        data[i][L+1] = g_lp
    else:
        data[i][L+1] = g

    _display_g = (min(_display_g[0], g_lp), max(_display_g[1], g_lp))
    # data[i][L+2] = _display_g[0]
    # data[i][L+3] = _display_g[1]
    # print(f">> {i:5d} {ts:18.6f} {data[i][1]:12.6f} {g:6.2f} {g_lp:6.2f} {_display_g[0]:6.2f} {_display_g[1]:6.2f}")

    print(f"** {int(data[i][0]):5d} {data[i][TS]:12.6f} {data[i][VS]:12.6f} {' '.join([f'{v:8.2f}' for v in data[i][L-2:L+5]])} || {data[i][L+1]-data[i][L+3]:8.2f}") #  // {data[i][VS]:8.2f}

    # if dataref_value(DREFS.Y_AGL) < 10 and dataref_value(DREFS.GROUND_SPEED) > 60:
    #     print(f"{data[-1][0].strftime('%S.%f')}, vs={round(vs,2)} g={round(g, 2)} lpg={round(g_lp, 2)}")
