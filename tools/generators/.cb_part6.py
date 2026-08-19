
    # ---- G. DATA SCIENCE --------------------------------------------------

    DS_KB = [
        (("pandas read csv", "read csv pandas"),
         "Read CSV into a DataFrame, sir:\nimport pandas as pd\ndf = pd.read_csv('file.csv')"
         "\nHandy args: parse_dates=['date'], usecols=[...], nrows=1000."),
        (("pandas dataframe basics", "pandas head describe"),
         "DataFrame first look, sir:\ndf.head()/df.tail() peek\ndf.info() types + nulls\n"
         "df.describe() numeric summary\ndf.shape gives rows x columns."),
        (("pandas filter rows", "loc iloc pandas"),
         "Select and filter, sir:\ndf['col'] series; df[['a','b']] frame\ndf.loc[df.age > 30,"
         " ['name','age']] label-based\ndf.iloc[0:5, 0:2] position-based\nmask = df.city.isin("
         "['Delhi','Mumbai'])"),
        (("pandas groupby", "group by pandas"),
         "Split-apply-combine, sir:\ndf.groupby('dept')['salary'].agg(['mean', 'max'])\n"
         "df.groupby(['dept','year']).size()\nPivot flavor: df.pivot_table(index='dept', "
         "columns='year', values='sales', aggfunc='sum')"),
        (("pandas merge", "concat pandas"),
         "Combine DataFrames, sir:\npd.merge(left, right, on='id', how='inner')  # left/right/"
         "outer\npd.concat([df1, df2], axis=0)  # stack rows\ndf1.join(df2, lsuffix='_1')  # index-based"),
        (("pivot table pandas",),
         "Reshape summaries, sir:\ndf.pivot_table(values='sales', index='region', columns='quarter',"
         " aggfunc='sum', fill_value=0, margins=True)\nmelt() reverses wide to long."),
        (("pandas missing values", "fillna pandas"),
         "Missing data triage, sir:\ndf.isna().sum() counts\ndf.dropna(subset=['age']) removes\n"
         "df['age'].fillna(df['age'].median()) fills\nTime series: df.interpolate()."),
        (("pandas apply", "apply function pandas"),
         "Row-wise transforms, sir:\ndf['full'] = df.apply(lambda r: r.a + ' ' + r.b, axis=1)\n"
         "df['col'].map(str.title)\nVectorize when possible - np.where(df.age > 18, 'adult', 'minor')"
         " beats apply."),
        (("sort_values pandas", "value_counts"),
         "Order and count, sir:\ndf.sort_values('col', ascending=False)\ndf.nlargest(5, 'score')\n"
         "df['city'].value_counts(normalize=True)  # frequency share"),
        (("pandas datetime", "to_datetime"),
         "Datetime handling, sir:\ndf['date'] = pd.to_datetime(df['date'], errors='coerce')\n"
         "df.set_index('date').resample('M').sum()\nAccessors: df.date.dt.year, .dt.month, .dt.dayofweek."),
        (("pandas to csv", "export dataframe"),
         "Export results, sir:\ndf.to_csv('out.csv', index=False)\ndf.to_excel('out.xlsx', sheet_name="
         "'Report')\nMulti-sheet needs pd.ExcelWriter as a context manager."),
        (("numpy array", "create numpy array"),
         "NumPy arrays, sir:\nimport numpy as np\na = np.array([[1, 2], [3, 4]])\nnp.zeros((3, 3)),"
         " np.ones(5), np.arange(0, 10, 2), np.linspace(0, 1, 11)\nVectorized math: a * 2 + 1 elementwise."),
        (("numpy indexing slicing",),
         "Index and slice arrays, sir:\na[0, 1], a[:, 0] column, a[::-1] reverse\nBoolean masks: a[a > 2]"
         " = 0\nFancy indexing: a[[0, 2], [1, 0]] picks pairs."),
        (("numpy broadcasting",),
         "Broadcasting stretches shapes without copying, sir:\n(3, 3) matrix + (3,) row vector adds per"
         " row automatically\nRules align trailing dimensions; size-1 dims stretch. np.newaxis inserts axes."),
        (("numpy random numbers",),
         "Random numbers, sir:\nrng = np.random.default_rng(42)  # seeded, modern API\nrng.integers(0, 10,"
         " size=(2, 3))\nrng.normal(loc=0, scale=1, size=1000)\nrng.choice(names, size=3, replace=False)"),
        (("numpy statistics",),
         "Descriptive stats, sir:\na.mean(axis=0), np.median(a), a.std(), a.var()\nnp.percentile(a, [25, 50,"
         " 75]) quartiles\ncorr = np.corrcoef(x, y)[0, 1]"),
        (("matplotlib line plot", "plot python matplotlib"),
         "Line plots, sir:\nimport matplotlib.pyplot as plt\nplt.plot(x, y, label='series')\nplt.xlabel('t');"
         " plt.ylabel('v'); plt.legend(); plt.title('Signal')\nplt.show()"),
        (("matplotlib subplots",),
         "Grids of plots, sir:\nfig, axes = plt.subplots(2, 2, figsize=(10, 6))\naxes[0, 0].plot(x, y)"
         "\nfig.suptitle('Overview')\nfig.tight_layout()"),
        (("histogram matplotlib",),
         "Histograms show distributions, sir:\nplt.hist(data, bins=30, edgecolor='white')\nNormalize with"
         " density=True; compare groups by overlaying alpha=0.6."),
        (("scatter plot matplotlib",),
         "Scatter plots reveal relationships, sir:\nplt.scatter(x, y, c=labels, s=sizes, alpha=0.6, cmap="
         "'viridis')\nplt.colorbar() decodes c."),
        (("bar chart matplotlib",),
         "Bar charts compare categories, sir:\nplt.bar(cats, vals)\nHorizontal: plt.barh\nGrouped: offset x"
         " positions per series; annotate with plt.bar_label(bars)."),
        (("savefig matplotlib", "save plot image"),
         "Save figures, sir:\nplt.savefig('chart.png', dpi=300, bbox_inches='tight')\nPDF/SVG for print "
         "quality; call before plt.show()."),
        (("seaborn plots",),
         "Seaborn dresses matplotlib statistically, sir:\nimport seaborn as sns\nsns.histplot(df, x='age',"
         " hue='group', kde=True)\nsns.heatmap(df.corr(), annot=True, cmap='coolwarm')\nsns.pairplot(df, hue="
         "'species')"),
    ]
