import streamlit as st
import pandas as pd
import plotly.express as px
import io
import chardet  # For auto-detecting file encoding

# Layout
st.set_page_config(page_title="Supernova Cleaner", layout="wide")

# CSS
def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

local_css("style.css")

# Initialize df as None at module level
df = None

def highlight_changed_cells(cleaned_df, raw_df):
    raw_aligned = raw_df.loc[cleaned_df.index, cleaned_df.columns]
    theme_base = st.get_option("theme.base")
    highlight_color = "rgba(255, 193, 7, 0.28)" if theme_base == "dark" else "rgba(255, 235, 59, 0.45)"

    changed = cleaned_df.ne(raw_aligned) | cleaned_df.isna().ne(raw_aligned.isna())

    # CHANGED: date highlighting now uses whatever column was tagged as 'date' type,
    # not a hardcoded 'Date' column name
    for col in cleaned_df.columns:
        if col in raw_aligned.columns and col in st.session_state.get('col_roles', {}):
            if st.session_state['col_roles'][col] == 'date':
                cleaned_dates = pd.to_datetime(cleaned_df[col], errors="coerce").dt.strftime("%Y-%m-%d")
                raw_dates = pd.to_datetime(raw_aligned[col], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
                raw_date_text = raw_aligned[col].astype(str).where(raw_aligned[col].notna(), "")
                changed[col] = raw_dates.notna() & cleaned_dates.notna() & (raw_date_text != cleaned_dates)

    def style_row(row):
        return [f"background-color: {highlight_color}" if changed.loc[row.name, col] else "" for col in row.index]

    return cleaned_df.style.apply(style_row, axis=1)

# ADDED: Sniffs each column and guesses what type of data it holds.
# Returns a dict like {'OrderDate': 'date', 'Price': 'numeric', ...}
def detect_column_roles(df):
    roles = {}
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(20)

        # Try parsing as dates
        try:
            parsed = pd.to_datetime(sample, format="mixed", errors="coerce")
            if parsed.notna().mean() >= 0.7:
                roles[col] = "date"
                continue
        except Exception:
            pass

        # Try parsing as numbers
        numeric = pd.to_numeric(df[col], errors="coerce")
        if numeric.notna().mean() >= 0.6:
            roles[col] = "numeric"
            continue

        roles[col] = "text"

    return roles


def is_identifier_column(col_name, series):
    lowered = col_name.lower()
    identifier_name = (
        "id" in lowered
        or lowered.endswith("_no")
        or lowered.endswith("no")
        or "number" in lowered
        or "code" in lowered
        or "ref" in lowered
        or "serial" in lowered
    )

    if not identifier_name:
        return False

    unique_ratio = series.dropna().nunique() / max(len(series.dropna()), 1)
    return unique_ratio > 0.8


def top_category_by_metric(df, category_col, metric_col):
    usable = df[[category_col, metric_col]].dropna(subset=[category_col, metric_col])
    if usable.empty:
        return None, None

    totals = usable.groupby(category_col, dropna=False)[metric_col].sum()
    if totals.empty:
        return None, None

    top_category = totals.idxmax()
    top_total = totals.loc[top_category]
    return top_category, top_total


def identify_text_duplicates(series):
    duplicates_map = {}
    for val in series.dropna().unique():
        val_str = str(val).strip()
        lower_val = val_str.lower()
        if lower_val not in duplicates_map:
            duplicates_map[lower_val] = []
        duplicates_map[lower_val].append(val_str)
    return {k: v for k, v in duplicates_map.items() if len(v) > 1}


def standardize_text_column(series):
    # Trim all values
    trimmed = series.astype(str).str.strip()
    
    # Identify case-insensitive duplicates
    duplicates_map = identify_text_duplicates(trimmed)
    
    # Build standardization mapping
    standardization_map = {}
    
    # For each duplicate group, find the most frequent variant and convert to Title Case
    for lower_val, variants in duplicates_map.items():
        variant_counts = trimmed[trimmed.str.lower() == lower_val].value_counts()
        if len(variant_counts) > 0:
            most_frequent = variant_counts.index[0]
        else:
            # Fallback to first variant if no counts
            most_frequent = variants[0]
        # Convert the most frequent variant to Title Case for consistency
        standardization_map[lower_val] = most_frequent.title()
    
    # Apply standardization
    result = series.astype(str).str.strip()
    
    # Replace all variants with their standardized (Title Case) form
    for lower_val, standard_val in standardization_map.items():
        mask = result.str.lower() == lower_val
        result[mask] = standard_val
    
    # Apply Title Case to any remaining values not in the mapping
    for idx in result.index:
        val = result[idx]
        if pd.notna(val) and str(val).lower() not in standardization_map:
            result[idx] = str(val).title()
    
    return result, standardization_map

with st.container():
    st.markdown('<div class="hero">', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        st.image("glitch.gif")

    with col2:
        st.title("Supernova Cleaner")
        st.markdown('<h3 class="hero-subheader">Transform your messy data into stellar insights.</h3>', unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader("Upload your data file", type=["csv", "xlsx", "xls"])

        if uploaded_file is None:
            st.info("Please upload a CSV or Excel file to begin.")

        # Show uploaded file
        if uploaded_file is not None:
            if uploaded_file.name.endswith('.csv'):
                # Try reading with UTF-8 first (most common encoding)
                try:
                    df = pd.read_csv(uploaded_file)
                except UnicodeDecodeError:
                    # If UTF-8 fails, auto-detect the file's encoding 
                    uploaded_file.seek(0)
                    raw_data = uploaded_file.read() 
                    detected = chardet.detect(raw_data) 
                    encoding = detected['encoding']
                    
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding=encoding)
            else:
                df = pd.read_excel(uploaded_file)

            if 'toast_shown' not in st.session_state:
                st.toast('File uploaded successfully!', icon='✅')
                st.session_state['toast_shown'] = True

            rows, cols = df.shape

            tab1, tab2, tab3 = st.tabs(["📂 Uploaded Data", "ℹ️ Data Types & Missing Values", "📈 Statistics"])

            with tab1:
                st.dataframe(df)
                st.caption(f"Rows: {rows}  •  Columns: {cols}")

            with tab2:
                col_type1, col_type2 = st.columns(2)
                with col_type1:
                    st.write("**Column Data Types**")
                    st.dataframe(df.dtypes.astype(str).rename("Data Type"), use_container_width=True)
                with col_type2:
                    st.write("**Missing Values Count**")
                    st.dataframe(df.isnull().sum().rename("Missing Values"), use_container_width=True)

            with tab3:
                st.write(df.describe())

    st.markdown('</div>', unsafe_allow_html=True)

# Auto-detect column roles and store them in session state so other
# parts of the app (like highlight_changed_cells) can reference them too
if df is not None:
    if 'col_roles' not in st.session_state or st.session_state.get('last_file') != uploaded_file.name:
        st.session_state['col_roles'] = detect_column_roles(df)
        st.session_state['last_file'] = uploaded_file.name

    # Option to confirm or adjust detected roles before cleaning
    st.subheader("🔍 Confirm Column Roles")
    st.caption("Roles below are auto-detected. Adjust if needed before cleaning. 'Skip' will exclude the column from cleaning operations.")

    role_options = ["date", "numeric", "text", "skip"]
    updated_roles = {}

    role_cols = st.columns(min(4, len(df.columns)))
    for i, col in enumerate(df.columns):
        detected = st.session_state['col_roles'].get(col, "text")
        with role_cols[i % len(role_cols)]:
            updated_roles[col] = st.selectbox(
                label=col,
                options=role_options,
                index=role_options.index(detected),
                key=f"role_{col}"
            )

    st.session_state['col_roles'] = updated_roles

    # Option to choose which numeric columns should have negative values fixed (converted to positive)
    numeric_cols = [c for c, r in updated_roles.items() if r == "numeric"]
    fix_negatives_cols = []
    if numeric_cols:
        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("➕ Fix Negative Values")
        st.caption("Select numeric columns where negative values should be converted to positive.")
        fix_negatives_cols = st.multiselect(
            "Columns to fix Negatives:",
            options=numeric_cols,
            default=[]
        )

    if st.button("✨ Clean Data"):
        df_cleaned = df.drop_duplicates().copy()

        for col, role in updated_roles.items():
            if role == "skip":
                continue

            elif role == "date":
                df_cleaned[col] = pd.to_datetime(df_cleaned[col], errors='coerce', format='mixed').dt.date
                df_cleaned = df_cleaned.dropna(subset=[col])

            elif role == "numeric":
                df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors='coerce')
                df_cleaned[col] = df_cleaned[col].fillna(df_cleaned[col].mean())

                if col in fix_negatives_cols:
                    df_cleaned[col] = df_cleaned[col].abs()
            # Text standardization
            elif role == "text":
                df_cleaned[col], text_mappings = standardize_text_column(df_cleaned[col])
                if 'text_standardization_mappings' not in st.session_state:
                    st.session_state['text_standardization_mappings'] = {}
                st.session_state['text_standardization_mappings'][col] = text_mappings

        # Persist cleaned data and metadata so visualizations survive user interactions
        st.session_state['df_cleaned'] = df_cleaned
        st.session_state['raw_df'] = df
        st.session_state['cleaned_file_ext'] = 'csv' if uploaded_file.name.lower().endswith('.csv') else 'excel'
        st.session_state['updated_roles'] = updated_roles
        st.session_state['cleaned_results_for'] = uploaded_file.name

        st.success("Data cleaning complete! View and download below.")

    # If cleaning has been run for the current file, show comparison and dashboard
    if 'df_cleaned' in st.session_state and st.session_state.get('cleaned_results_for') == uploaded_file.name:
        df_cleaned = st.session_state['df_cleaned']
        raw_df = st.session_state.get('raw_df', df)

        st.divider()
        result_tab, insights_tab = st.tabs(["🧾 Raw vs Cleaned", "📊 Trends & Insights"])

        with result_tab:
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("❌ Raw Data")
                st.dataframe(raw_df)

            with col2:
                st.subheader("✅ Cleaned Data")
                st.dataframe(highlight_changed_cells(df_cleaned, raw_df), use_container_width=True)

            # Download button: return the cleaned file in same format as uploaded
            file_ext = st.session_state.get('cleaned_file_ext', 'csv')
            download_col1, download_col2 = st.columns([1,3])
            with download_col1:
                if file_ext == 'csv':
                    csv_bytes = df_cleaned.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="Download Cleaned CSV",
                        data=csv_bytes,
                        file_name=f"cleaned_{uploaded_file.name}",
                        mime='text/csv'
                    )
                else:
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                        df_cleaned.to_excel(writer, index=False)
                    buffer.seek(0)
                    st.download_button(
                        label="Download cleaned Excel",
                        data=buffer,
                        file_name=f"cleaned_{uploaded_file.name}",
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    )

        with insights_tab:
            updated_roles = st.session_state.get('updated_roles', updated_roles)
            date_cols = [c for c, r in updated_roles.items() if r == "date"]
            num_cols = [c for c, r in updated_roles.items() if r == "numeric"]
            cat_cols = [c for c, r in updated_roles.items() if r == "text"]
            analysis_num_cols = [c for c in num_cols if not is_identifier_column(c, df_cleaned[c])]

            sel_key = f"selected_num_{uploaded_file.name}"
            if analysis_num_cols and (sel_key not in st.session_state or st.session_state.get(sel_key) not in analysis_num_cols):
                st.session_state[sel_key] = analysis_num_cols[0]

            if analysis_num_cols:
                # Top Selection Bar
                st.subheader("🖥️ Trends and Insights")
                selected_num = st.selectbox("Select Variable to Analyze:", options=analysis_num_cols, key=sel_key)

                # --- ROW 1: TRENDS & DISTRIBUTIONS ---
                trend_col, bar_col = st.columns(2)

                with trend_col:
                    with st.container(border=True):
                        if date_cols:
                            date_choice = date_cols[0]
                            df_trend = df_cleaned.sort_values(by=date_choice)
                            fig_line = px.area(df_trend, x=date_choice, y=selected_num, title=f"📈 {selected_num} Trend over Time")
                            
                            fig_line.update_traces(line_color='#00d4ff', fillcolor='rgba(0, 212, 255, 0.1)')
                            fig_line.update_layout(
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                xaxis=dict(showgrid=False),
                                yaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                                font_color="white"
                            )
                            st.plotly_chart(fig_line, use_container_width=True)

                with bar_col:
                    with st.container(border=True):
                        if cat_cols:
                            cat_choice = cat_cols[0]
                            fig_bar = px.bar(df_cleaned, x=cat_choice, y=selected_num, title=f"📊 {selected_num} by {cat_choice}", color=cat_choice)

                            fig_bar.update_layout(
                                plot_bgcolor='rgba(0,0,0,0)',
                                paper_bgcolor='rgba(0,0,0,0)',
                                xaxis=dict(showgrid=False),
                                yaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                                font_color="white"
                            )
                            st.plotly_chart(fig_bar, use_container_width=True)

                # --- ROW 2: COMPOSITION & INSIGHTS ---
                bottom_col1, bottom_col2 = st.columns(2)

                with bottom_col1:
                    with st.container(border=True):
                        if cat_cols:
                            fig_pie = px.pie(df_cleaned, names=cat_cols[0], hole=0.4, title=f"Distribution of {cat_cols[0]}")
                            fig_pie.update_layout(
                                paper_bgcolor='rgba(0,0,0,0)',
                                font_color="white",
                                showlegend=True
                            )
                            st.plotly_chart(fig_pie, use_container_width=True)

                with bottom_col2:
                    with st.container(border=True):
                        st.subheader("💡 Quick Insights")
                        metric_col1, metric_col2, metric_col3 = st.columns(3)

                        if cat_cols and analysis_num_cols:
                            top_val, top_total = top_category_by_metric(df_cleaned, cat_cols[0], selected_num)
                            with metric_col1:
                                st.metric(label=f"Top {cat_cols[0]} by {selected_num}", value=str(top_val), delta=f"Total {selected_num}: {top_total:,.0f}" if top_total is not None else None)
                        elif cat_cols:
                            top_val = df_cleaned[cat_cols[0]].mode()[0]
                            with metric_col1:
                                st.metric(label=f"Most Frequent {cat_cols[0]}", value=str(top_val))

                        if analysis_num_cols:
                            total_val = df_cleaned[selected_num].sum()
                            avg_val = df_cleaned[selected_num].mean()
                            
                            with metric_col2:
                                st.metric(label=f"Total {selected_num}", value=f"{total_val:,.0f}")
                            with metric_col3:
                                st.metric(label="Average", value=f"{avg_val:,.2f}")
                            
                            st.info(f"📖 **Summary:** On average, each entry represents **{avg_val:.2f}** in {selected_num}. The total combined volume is **{total_val:,.2f}**.")
            else:
                if num_cols:
                    st.info("No analysis-ready numeric columns available. Columns that look like IDs are excluded from charts and quick insights.")
                else:
                    st.info("No numeric columns available for visualization.")