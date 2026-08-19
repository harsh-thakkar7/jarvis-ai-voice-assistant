
    DS_ML_KB = [
        (("jupyter notebook tips", "jupyter shortcuts"),
         "Jupyter essentials, sir: Shift+Enter runs a cell; A/B insert above/below; DD deletes; M/Y switch "
         "markdown/code. Magics: %timeit, %%time, %matplotlib inline, !pip install pkg."),
        (("train test split sklearn",),
         "Hold-out evaluation, sir:\nfrom sklearn.model_selection import train_test_split\nX_tr, X_te, y_tr,"
         " y_te = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)"),
        (("linear regression sklearn", "fit linear regression"),
         "Linear regression, sir:\nfrom sklearn.linear_model import LinearRegression\nmodel = LinearRegression()"
         ".fit(X_train, y_train)\npreds = model.predict(X_test)\ncoef_ and intercept_ explain the fit; R^2 via "
         "model.score(X_test, y_test)."),
        (("logistic regression sklearn",),
         "Logistic regression classifies probabilities, sir: linear model squashed by sigmoid. from sklearn."
         "linear_model import LogisticRegression; tune C for regularization strength."),
        (("random forest sklearn",),
         "Random forest = bagged decision trees voting, sir:\nfrom sklearn.ensemble import RandomForestClassifier"
         "\nrf = RandomForestClassifier(n_estimators=300).fit(X_tr, y_tr)\nrf.feature_importances_ ranks drivers."),
        (("decision tree sklearn",),
         "Decision trees split features greedily, sir:\nfrom sklearn.tree import DecisionTreeClassifier, export_text"
         "\nprint(export_text(tree.fit(X, y), feature_names=cols))\nDepth-limit or they memorize noise."),
        (("kmeans clustering", "k means clustering"),
         "K-Means groups unlabeled data, sir:\nfrom sklearn.cluster import KMeans\nkm = KMeans(n_clusters=3, "
         "n_init=10).fit(X_scaled)\nkm.labels_, km.cluster_centers_\nElbow/inertia or silhouette score pick k."),
        (("knn classifier", "k nearest neighbors"),
         "KNN votes with neighbors, sir:\nfrom sklearn.neighbors import KNeighborsClassifier\nknn = "
         "KNeighborsClassifier(n_neighbors=5).fit(X_scaled, y_tr)\nScale features first - distance is everything."),
        (("svm sklearn", "support vector machine"),
         "SVMs find maximum-margin boundaries, sir:\nfrom sklearn.svm import SVC\nsvc = SVC(kernel='rbf', C=1.0,"
         " gamma='scale').fit(X_scaled, y)\nKernels bend space; C trades margin width for violations."),
        (("naive bayes classifier",),
         "Naive Bayes multiplies feature likelihoods assuming independence - fast baseline for text spam, sir:"
         "\nfrom sklearn.naive_bayes import MultinomialNB\nnb.fit(X_counts, y); nb.predict(new_docs)"),
        (("gradient boosting xgboost", "lightgbm"),
         "Gradient boosting grows trees that correct predecessors' errors, sir: HistGradientBoostingClassifier"
         " (sklearn) or XGBoost/LightGBM for speed. Watch learning_rate, max_depth, early stopping."),
        (("neural network keras", "keras model"),
         "Tiny Keras network, sir:\nfrom tensorflow import keras\nm = keras.Sequential([\n  keras.layers.Dense(64,"
         " activation='relu'),\n  keras.layers.Dense(1, activation='sigmoid')])\nm.compile(optimizer='adam', loss="
         "'binary_crossentropy', metrics=['accuracy'])\nm.fit(X, y, epochs=10, validation_split=0.2)"),
        (("overfitting underfitting", "regularization machine learning"),
         "Overfitting memorizes train, fails test; underfitting misses both, sir. Remedies: more data, simpler"
         " model, dropout, L2 weight decay, early stopping. Learning curves diagnose which."),
        (("cross validation sklearn", "cross_val_score"),
         "Cross-validation rotates folds for honest scores, sir:\nfrom sklearn.model_selection import "
         "cross_val_score\nscores = cross_val_score(model, X, y, cv=5)\nscores.mean(), scores.std()"),
        (("confusion matrix precision recall", "precision recall f1"),
         "Classification metrics, sir:\nfrom sklearn.metrics import confusion_matrix, classification_report\n"
         "Precision = TP/(TP+FP) 'when I say yes am I right'; Recall = TP/(TP+FN) 'did I catch all'; F1 balances them."),
        (("roc auc curve",),
         "ROC curves trade recall against false positives across thresholds, sir: from sklearn.metrics import "
         "roc_auc_score; roc_auc_score(y, proba). 0.5 coin-flip, 0.9 strong, 1.0 perfect."),
        (("feature scaling standard scaler",),
         "Scale features so distance models behave, sir:\nfrom sklearn.preprocessing import StandardScaler\n"
         "X_scaled = StandardScaler().fit_transform(X)\nMinMaxScaler squeezes to [0, 1]; fit on train only."),
        (("one hot encoding categorical",),
         "Encode categories, sir:\npd.get_dummies(df, columns=['city'])\nOr sklearn OneHotEncoder(handle_unknown="
         "'ignore') inside pipelines. High-cardinality? Target/hash encoding instead."),
        (("sklearn pipeline",),
         "Pipelines chain preprocessing + model safely, sir:\nfrom sklearn.pipeline import make_pipeline\npipe = "
         "make_pipeline(StandardScaler(), LogisticRegression())\npipe.fit(X_tr, y_tr); cross_val_score(pipe, X, y)"
         " - no leakage."),
        (("grid search hyperparameter tuning",),
         "Tune hyperparameters exhaustively, sir:\nfrom sklearn.model_selection import GridSearchCV\ngs = "
         "GridSearchCV(pipe, param_grid={'logisticregression__C': [0.1, 1, 10]}, cv=5)\ngs.best_params_, gs.best_score_"),
        (("save model joblib", "persist trained model"),
         "Persist trained models, sir:\nimport joblib\njoblib.dump(model, 'model.joblib')\nlater = joblib.load('model.joblib')"
         "\nMatch versions between training and serving environments."),
    ]

    for _i, (_trg, _rep) in enumerate(DS_KB + DS_ML_KB):
        _cb_kb("cb_ds", _i, _trg, _rep)
